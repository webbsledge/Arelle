from arelle import ModelDocument
from arelle.ModelXbrl import ModelXbrl
from arelle.ValidateXbrl import ValidateXbrl
from arelle.utils.validate.Concepts import isExtensionUri


def checkInlineDocumentEncoding(val: ValidateXbrl, encodings: list[str], taxonomyUrlPrefixes: frozenset[str]) -> list[ModelDocument.ModelDocument]:
    """
    Checks the encoding of inline documents against a list of allowed encodings.
    :param val: validateXbrl object containing the modelXbrl with the documents to check.
    :param encodings: lower case list of allowed encodings (e.g., ['utf-8', 'iso-8859-1', 'utf-8-sig'])
    :param taxonomyUrlPrefixes: frozenset of URL prefixes that identify taxonomy documents (e.g., {'http://www.xbrl.org/2003/linkbase', 'http://www.xbrl.org/2003/instance'})
    :return: list of ModelDocument objects that have a disallowed encoding.
    """
    docsWithDisallowedEncoding = []
    for modelDocument in val.modelXbrl.urlDocs.values():
        if not isExtensionUri(modelDocument.uri, val.modelXbrl, taxonomyUrlPrefixes):
            continue
        if modelDocument.type != ModelDocument.Type.INLINEXBRLDOCUMENTSET:
            if modelDocument.documentEncoding is None or modelDocument.documentEncoding.lower() not in encodings:
                docsWithDisallowedEncoding.append(modelDocument)
    return docsWithDisallowedEncoding
