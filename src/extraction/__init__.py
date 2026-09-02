"""
Entity and Relation Extraction Module
Provides Pydantic schemas for knowledge graph entities and relations.
"""

from .schemas import (
    # Entities
    DiseaseEntity,
    SymptomEntity,
    MedicationEntity,
    DepartmentEntity,
    ExaminationEntity,
    TreatmentEntity,
    BodyPartEntity,
    MedicalConceptEntity,
    # Relations
    HasSymptomRelation,
    MayIndicateRelation,
    BelongsToDepartmentRelation,
    TreatedByDrugRelation,
    TreatsDiseaseRelation,
    HasSideEffectRelation,
    DrugInteractionRelation,
    NeedsExaminationRelation,
    AffectsBodyPartRelation,
    ForDiseaseRelation,
    HandlesDiseaseRelation,
    DiseaseRelatedRelation,
    # Comprehensive
    DiseaseExtractionResult,
    # Utilities
    get_all_entity_types,
    get_all_relation_types,
)

__all__ = [
    # Entities
    "DiseaseEntity",
    "SymptomEntity",
    "MedicationEntity",
    "DepartmentEntity",
    "ExaminationEntity",
    "TreatmentEntity",
    "BodyPartEntity",
    "MedicalConceptEntity",
    # Relations
    "HasSymptomRelation",
    "MayIndicateRelation",
    "BelongsToDepartmentRelation",
    "TreatedByDrugRelation",
    "TreatsDiseaseRelation",
    "HasSideEffectRelation",
    "DrugInteractionRelation",
    "NeedsExaminationRelation",
    "AffectsBodyPartRelation",
    "ForDiseaseRelation",
    "HandlesDiseaseRelation",
    "DiseaseRelatedRelation",
    # Comprehensive
    "DiseaseExtractionResult",
    # Utilities
    "get_all_entity_types",
    "get_all_relation_types",
]
