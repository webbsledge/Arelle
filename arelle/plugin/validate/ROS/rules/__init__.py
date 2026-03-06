"""
See COPYRIGHT.md for copyright information.
"""
from __future__ import annotations

from collections.abc import Iterable

from arelle.ModelXbrl import ModelXbrl
from arelle.utils.validate.Facts import getNegativeFacts
from arelle.utils.validate.Facts import getRequiredFactMissing
from arelle.utils.validate.Validation import Validation


def errorOnMissingRequiredFact(
        modelXbrl: ModelXbrl,
        conceptLn: str,
        code: str,
        message: str,
) -> Iterable[Validation]:
    """
    Yields an error if a fact with the given localName is not tagged with a non-nil value.
    :return: Yields validation errors.
    """
    if getRequiredFactMissing(modelXbrl, conceptLn, byQname=False):
        yield Validation.error(conceptLn=conceptLn, codes=code, msg=message)


def errorOnNegativeFact(
        modelXbrl: ModelXbrl,
        conceptLn: str,
        code: str,
        message: str,
) -> Iterable[Validation]:
    """
    Yields an error for each fact with the given localName that has a negative value.
    :return: Yields validation errors.
    """
    for fact in getNegativeFacts(modelXbrl, conceptLn, byQname=False):
        yield Validation.error(codes=code, modelObject=fact, msg=message)
