"""
See COPYRIGHT.md for copyright information.
"""
from __future__ import annotations

import os
from typing import Any, cast

from collections import Counter
from collections.abc import Iterable
from decimal import Decimal

from arelle.typing import TypeGetText
from arelle.ValidateXbrl import ValidateXbrl
from collections import defaultdict
from math import isnan
from lxml.etree import _Comment, _ElementTree, _Entity, _ProcessingInstruction
from arelle import ModelDocument
from arelle.ModelInstanceObject import ModelInlineFact, ModelUnit
from arelle.ModelValue import qname
from arelle.ModelXbrl import ModelXbrl
from arelle.PythonUtil import strTruncate
from arelle.utils.Contexts import partitionModelXbrlContexts
from arelle.utils.Units import partitionModelXbrlUnits
from arelle.utils.PluginHooks import ValidationHook
from arelle.utils.validate.Decorator import validation
from arelle.utils.validate.Validation import Validation
from arelle.ValidateXbrlCalcs import inferredDecimals, rangeValue
from arelle.XbrlConst import qnXbrliMonetaryItemType, qnXbrliXbrl, xhtml
from arelle.XmlValidateConst import VALID
from ..ValidationPluginExtension import EQUITY, PRINCIPAL_CURRENCY, TURNOVER_REVENUE
from ..PluginValidationDataExtension import MANDATORY_ELEMENTS,  SCHEMA_PATTERNS, TR_NAMESPACES, PluginValidationDataExtension


def checkFileEncoding(modelXbrl: ModelXbrl) -> None:
    for doc in modelXbrl.urlDocs.values():
        if doc.documentEncoding.lower() != "utf-8":
            modelXbrl.error("ROS.documentEncoding",
                            _("iXBRL documents submitted to Revenue should be UTF-8 encoded: %(encoding)s"),
                            modelObject=doc, encoding=doc.documentEncoding)


def checkFileExtensions(modelXbrl: ModelXbrl) -> None:
    for doc in modelXbrl.urlDocs.values():
        if doc.type == ModelDocument.Type.INLINEXBRL:
            _baseName, _baseExt = os.path.splitext(doc.basename)
            if _baseExt not in (".xhtml", ".html", ".htm", ".ixbrl", ".xml", ".xhtml"):
                modelXbrl.error("ROS.fileNameExtension",
                                _("The list of acceptable file extensions for upload is: html, htm, ixbrl, xml, xhtml: %(fileName)s"),
                                modelObject=doc, fileName=doc.basename)


_: TypeGetText


@validation(
    hook=ValidationHook.XBRL_FINALLY,
)
def rule_main(
        pluginData: PluginValidationDataExtension,
        val: ValidateXbrl,
        *args: Any,
        **kwargs: Any,
) -> None:

    _xhtmlNs = "{{{}}}".format(xhtml)
    _xhtmlNsLen = len(_xhtmlNs)
    modelXbrl = val.modelXbrl
    modelDocument = modelXbrl.modelDocument
    if not modelDocument:
         return # never loaded properly

    _statusMsg = _("validating {0} filing rules").format(val.disclosureSystem.name)
    modelXbrl.profileActivity()
    modelXbrl.modelManager.showStatus(_statusMsg)
    if modelDocument.type == ModelDocument.Type.INSTANCE:
        modelXbrl.error("ROS:instanceMustBeInlineXBRL",
                        _("ROS expects inline XBRL instances."),
                        modelObject=modelXbrl)
    if modelDocument.type in (ModelDocument.Type.INLINEXBRL, ModelDocument.Type.INLINEXBRLDOCUMENTSET):
        checkFileExtensions(modelXbrl)
        checkFileEncoding(modelXbrl)
        for ixdsHtmlRootElt in modelXbrl.ixdsHtmlElements: # ix root elements for all ix docs in IXDS
            ixNStag = ixdsHtmlRootElt.modelDocument.ixNStag
            ixTags = set(ixNStag + ln for ln in ("nonNumeric", "nonFraction", "references", "relationship"))

        transformRegistryErrors = set()
        ixTargets = set()
        for ixdsHtmlRootElt in modelXbrl.ixdsHtmlElements:
            for elt in ixdsHtmlRootElt.iter():
                if isinstance(elt, (_Comment, _ElementTree, _Entity, _ProcessingInstruction)):
                    continue # comment or other non-parsed element
                if isinstance(elt, ModelInlineFact):
                    if elt.format is not None and elt.format.namespaceURI not in TR_NAMESPACES:
                        transformRegistryErrors.add(elt)
                    if elt.isEscaped:
                        modelXbrl.error("ROS.escapedHTML",
                                        _("Escaped (x)html fact content is not supported: %(element)s"),
                                        modelObject=elt, element=eltTag)
                eltTag = elt.tag
                if eltTag in ixTags:
                    ixTargets.add( elt.get("target") )
                else:
                    if eltTag.startswith(_xhtmlNs):
                        eltTag = eltTag[_xhtmlNsLen:]
                        if eltTag == "link" and elt.get("type") == "text/css":
                            modelXbrl.error("ROS.externalCssStyle",
                                            _("CSS must be embedded in the inline XBRL document: %(element)s"),
                                            modelObject=elt, element=eltTag)
                        elif ((eltTag in ("object", "script")) or
                              (eltTag == "a" and "javascript:" in elt.get("href","")) or
                              (eltTag == "img" and "javascript:" in elt.get("src",""))):
                            modelXbrl.error("ROS.embeddedCode",
                                            _("Inline XBRL documents MUST NOT contain embedded code: %(element)s"),
                                            modelObject=elt, element=eltTag)
                        elif eltTag == "img":
                            src = elt.get("src","").strip()
                            if not src.startswith("data:image"):
                                modelXbrl.warning("ROS.embeddedCode",
                                                  _("Images should be inlined as a base64-encoded string: %(element)s"),
                                                  modelObject=elt, element=eltTag)

        if len(ixTargets) > 1:
            modelXbrl.error("ROS:singleOutputDocument",
                            _("Multiple target instance documents are not supported: %(targets)s."),
                            modelObject=modelXbrl, targets=", ".join((t or "(default)") for t in ixTargets))

        if len(pluginData.getFilingTypes(modelXbrl)) != 1:
            modelXbrl.error("ROS:multipleFilingTypes",
                            _("Multiple filing types detected: %(filingTypes)s."),
                            modelObject=modelXbrl, filingTypes=", ".join(sorted(pluginData.getFilingTypes(modelXbrl))))
        if len(pluginData.getUnexpectedTaxonomyReferences(modelXbrl)):
            modelXbrl.error("ROS:unexpectedTaxonomyReferences",
                            _("Referenced schema(s) does not map to a taxonomy supported by Revenue (schemaRef): %(unexpectedReferences)s."),
                            modelObject=modelXbrl, unexpectedReferences=", ".join(sorted(pluginData.getUnexpectedTaxonomyReferences(modelXbrl))))

        # single document IXDS
        if pluginData.getNumIxDocs(modelXbrl) > 1:
            modelXbrl.warning("ROS:multipleInlineDocuments",
                              _("A single inline document should be submitted but %(numberDocs)s were found."),
                              modelObject=modelXbrl, numberDocs=pluginData.getNumIxDocs(modelXbrl))

        # build namespace maps
        nsMap = {}
        for prefix in ("ie-common", "bus", "uk-bus", "ie-dpl", "core"):
            if prefix in modelXbrl.prefixedNamespaces:
                nsMap[prefix] = modelXbrl.prefixedNamespaces[prefix]

        # build mandatory table by ns qname in use
        mandatory = set()
        for prefix in MANDATORY_ELEMENTS:
            if prefix in nsMap:
                ns = nsMap[prefix]
                for localName in MANDATORY_ELEMENTS[prefix]:
                    mandatory.add(qname(ns, prefix + ":" + localName))
        # document creator requirement
        if "bus" in nsMap:
            if qname("bus:NameProductionSoftware",nsMap) not in modelXbrl.factsByQname or qname("bus:VersionProductionSoftware",nsMap) not in modelXbrl.factsByQname:
                modelXbrl.warning("ROS:documentCreatorProductInformation",
                                  _("Please use the NameProductionSoftware tag to identify the software package and the VersionProductionSoftware tag to identify the version of the software package."),
                                  modelObject=modelXbrl)
        elif "uk-bus" in nsMap:
            if qname("uk-bus:NameAuthor",nsMap) not in modelXbrl.factsByQname or qname("uk-bus:DescriptionOrTitleAuthor",nsMap) not in modelXbrl.factsByQname:
                modelXbrl.warning("ROS:documentCreatorProductInformation",
                                  _("Revenue request that vendor, product and version information is embedded in the generated inline XBRL document using a single XBRLDocumentAuthorGrouping tuple. The NameAuthor tag should be used to identify the name and version of the software package."),
                                  modelObject=modelXbrl)


        schemeEntityIds = set()
        mapContext = {} # identify unique contexts and units
        mapUnit = {}
        hasCRO = False
        unsupportedSchemeContexts = []
        mismatchIdentifierContexts = []
        for context in modelXbrl.contexts.values():
            schemeEntityIds.add(context.entityIdentifier)
            scheme, entityId = context.entityIdentifier
            if scheme not in SCHEMA_PATTERNS:
                unsupportedSchemeContexts.append(context)
            elif not SCHEMA_PATTERNS[scheme].match(entityId):
                mismatchIdentifierContexts.append(context)
            if scheme == "http://www.cro.ie/":
                hasCRO = True
        for exemplar_context, *contexts in partitionModelXbrlContexts(modelXbrl).values():
            for context in contexts:
                mapContext[context] = exemplar_context

        if len(schemeEntityIds) > 1:
            modelXbrl.error("ROS:differentContextEntityIdentifiers",
                            _("Context entity identifier not all the same: %(schemeEntityIds)s."),
                            modelObject=modelXbrl, schemeEntityIds=", ".join(sorted(str(s) for s in schemeEntityIds)))
        if unsupportedSchemeContexts:
            modelXbrl.error("ROS:unsupportedContextEntityIdentifierScheme",
                            _("Context identifier scheme(s) is not supported: %(schemes)s."),
                            modelObject=unsupportedSchemeContexts,
                            schemes=", ".join(sorted(set(c.entityIdentifier[0] for c in unsupportedSchemeContexts))))
        if mismatchIdentifierContexts:
            modelXbrl.error("ROS:invalidContextEntityIdentifier",
                            _("Context entity identifier(s) lexically invalid: %(identifiers)s."),
                            modelObject=mismatchIdentifierContexts,
                            identifiers=", ".join(sorted(set(c.entityIdentifier[1] for c in mismatchIdentifierContexts))))

        for exemplar_unit, *units in partitionModelXbrlUnits(modelXbrl).values():
            for unit in units:
                mapUnit[unit] = exemplar_unit

        if hasCRO and "ie-common" in nsMap:
            mandatory.add(qname("ie-common:CompaniesRegistrationOfficeNumber", nsMap))  # type-ignore[arg-type]

        reportedMandatory = set()
        factForConceptContextUnitHash = defaultdict(list)

        for qn, facts in modelXbrl.factsByQname.items():
            if qn in mandatory:
                reportedMandatory.add(qn)
            for f in facts:
                if (f.parentElement.qname == qnXbrliXbrl and
                        (f.isNil or getattr(f,"xValid", 0) >= VALID) and f.context is not None and f.concept is not None and f.concept.type is not None):
                    factForConceptContextUnitHash[f.conceptContextUnitHash].append(f)

        missingElements = (mandatory - reportedMandatory) # | (reportedFootnoteIfNil - reportedFootnoteIfNil)

        if missingElements:
            modelXbrl.error("ROS:missingRequiredElements",
                            _("Required elements missing from document: %(elements)s."),
                            modelObject=modelXbrl, elements=", ".join(sorted(str(qn) for qn in missingElements)))

        aspectEqualFacts = defaultdict(dict) # dict [(qname,lang)] of dict(cntx,unit) of [fact, fact]
        decVals = {}
        for hashEquivalentFacts in factForConceptContextUnitHash.values():
            if len(hashEquivalentFacts) > 1:
                for f in hashEquivalentFacts: # check for hash collision by value checks on context and unit
                    cuDict = aspectEqualFacts[(f.qname,
                                               (f.xmlLang or "").lower() if f.concept.type.isWgnStringFactType else None)]
                    _matched = False
                    for (_cntx,_unit),fList in cuDict.items():
                        if (((_cntx is None and f.context is None) or (f.context is not None and f.context.isEqualTo(_cntx))) and
                                ((_unit is None and f.unit is None) or (f.unit is not None and f.unit.isEqualTo(_unit)))):
                            _matched = True
                            fList.append(f)
                            break
                    if not _matched:
                        cuDict[(f.context,f.unit)] = [f]
                for cuDict in aspectEqualFacts.values(): # dups by qname, lang
                    for fList in cuDict.values():  # dups by equal-context equal-unit
                        if len(fList) > 1:
                            f0 = fList[0]
                            _inConsistent = True
                            if f0.concept.isNumeric:
                                if any(f.isNil for f in fList):
                                    _inConsistent = not all(f.isNil for f in fList)
                                else: # not all have same decimals
                                    _d = inferredDecimals(f0)
                                    _v = f0.xValue
                                    _inConsistent = isnan(_v) # NaN is incomparable, always makes dups inconsistent
                                    decVals[_d] = _v
                                    aMax, bMin, _inclA, _inclB = rangeValue(_v, _d)
                                    for f in fList[1:]:
                                        _d = inferredDecimals(f)
                                        _v = f.xValue
                                        if isnan(_v):
                                            _inConsistent = True
                                            break
                                        if _d in decVals:
                                            _inConsistent |= _v != decVals[_d]
                                        else:
                                            decVals[_d] = _v
                                        a, b, _inclA, _inclB = rangeValue(_v, _d)
                                        if a > aMax: aMax = a
                                        if b < bMin: bMin = b
                                    if not _inConsistent:
                                        _inConsistent = (bMin < aMax)
                                    decVals.clear()
                            else: # string complete duplicates
                                _inConsistent = any(not f.isVEqualTo(f0) for f in fList[1:])
                            if _inConsistent:
                                modelXbrl.error("ROS.inconsistentDuplicateFacts",
                                                "Inconsistent duplicate fact values %(element)s: %(values)s, in contexts: %(contextIDs)s.",
                                                modelObject=fList, element=f0.qname,
                                                contextIDs=", ".join(sorted(set(f.contextID for f in fList))),
                                                values=", ".join(strTruncate(f.value,64) for f in fList))
                aspectEqualFacts.clear()
        del factForConceptContextUnitHash, aspectEqualFacts
    modelXbrl.profileActivity(_statusMsg, minTimeToShow=0.0)
    modelXbrl.modelManager.showStatus(None)


@validation(
    hook=ValidationHook.XBRL_FINALLY,
)
def rule_ros19(
        pluginData: PluginValidationDataExtension,
        val: ValidateXbrl,
        *args: Any,
        **kwargs: Any,
) -> Iterable[Validation]:
    """
    ROS: Rule 19: DPLTurnoverRevenue should be tested to be less than or equal to 10x the absolute value of Equity
    """
    def convertToDecimal(value):
        return Decimal(value) if isinstance(value, float) else cast(Decimal, value)
    equity_facts = val.modelXbrl.factsByLocalName.get(EQUITY, set())
    largest_equity_fact = None
    for e_fact in equity_facts:
        if e_fact.xValid >= VALID:
            if largest_equity_fact is None or abs(convertToDecimal(e_fact.xValue)) > abs(convertToDecimal(largest_equity_fact.xValue)):
                largest_equity_fact = e_fact

    turnover_facts = val.modelXbrl.factsByLocalName.get(TURNOVER_REVENUE, set())
    largest_turnover_fact = None
    for t_fact in turnover_facts:
        if t_fact.xValid >= VALID:
            if largest_turnover_fact is None or convertToDecimal(t_fact.xValue) > convertToDecimal(largest_turnover_fact.xValue):
                largest_turnover_fact = t_fact

    if (largest_equity_fact is not None and
            largest_turnover_fact is not None and
            convertToDecimal(largest_turnover_fact.xValue) > (10 * abs(convertToDecimal(largest_equity_fact.xValue)))):
        yield Validation.error(
            "ROS.19",
            _("Turnover / Revenue (DPLTurnoverRevenue) may exceed the maximum expected value. Please review the submission and, if correct, test your submission with Revenue Online's iXBRL test facility."),
            modelObject=[largest_equity_fact, largest_turnover_fact],
        )


@validation(
    hook=ValidationHook.XBRL_FINALLY,
)
def rule_ros20(
        pluginData: PluginValidationDataExtension,
        val: ValidateXbrl,
        *args: Any,
        **kwargs: Any,
) -> Iterable[Validation]:
    """
    ROS: Rule 20:PrincipalCurrencyUsedInBusinessReport must exist and its value must match the unit
    used for the majority of monetary facts.
    """
    principal_currency_facts = val.modelXbrl.factsByLocalName.get(PRINCIPAL_CURRENCY, set())
    principal_currency_values = set(fact.text for fact in principal_currency_facts)
    if len(principal_currency_values) != 1:
        yield Validation.error(
            "ROS.20",
            _("'PrincipalCurrencyUsedInBusinessReport' must exist and have a single value.  Values found: %(principal_currency_values)s."),
            modelObject=principal_currency_facts,
            principal_currency_values=principal_currency_values,
        )
    else:
        principal_currency_value = principal_currency_values.pop()
        monetary_facts = list(val.modelXbrl.factsByDatatype(False, qnXbrliMonetaryItemType))
        monetary_units = [list(fact.utrEntries)[0].unitName for fact in monetary_facts if fact.unit is not None]
        unit_counts = Counter(monetary_units)
        principal_currency_value_count = unit_counts[principal_currency_value]
        for unit, count in unit_counts.items():
            if count > principal_currency_value_count:
                yield Validation.warning(
                    "ROS.20",
                    _("'PrincipalCurrencyUsedInBusinessReport' has a value of %(principal_currency_value)s, "
                      "which must match the functional(majority) unit of the financial statement."),
                    modelObject=principal_currency_facts,
                    principal_currency_value=principal_currency_value,
                )
                break
