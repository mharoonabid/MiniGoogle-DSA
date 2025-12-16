"""
Mock Document Metadata Generator

Generates realistic document titles and metadata based on PMC IDs.
This is used when the actual CORD-19 dataset is not available.

For production, replace this with actual metadata extraction from JSON files.
"""

import json
import hashlib
from pathlib import Path

# COVID-19 research title templates
TITLE_TEMPLATES = [
    "Efficacy and Safety of {treatment} in {population}: A {study_type}",
    "{treatment} for Prevention of {condition}: Clinical Trial Results",
    "Impact of {intervention} on {outcome} in COVID-19 Patients",
    "Comparative Analysis of {treatment_a} versus {treatment_b} for {condition}",
    "{study_type} of {treatment} in {population} with {condition}",
    "Molecular Mechanisms of {virus} {process}: A Comprehensive Review",
    "Epidemiological Trends of {condition} During the COVID-19 Pandemic",
    "Vaccine Development Against {virus}: Current Progress and Challenges",
    "Long-term Effects of {condition} in Recovered COVID-19 Patients",
    "Risk Factors Associated with {outcome} in {population}",
    "Diagnostic Accuracy of {test} for {condition} Detection",
    "Immunological Responses to {treatment} in {population}",
    "Global Distribution and Evolution of {virus} Variants",
    "Mental Health Implications of COVID-19 in {population}",
    "Telemedicine Applications in {specialty} During the Pandemic"
]

TREATMENTS = [
    "mRNA Vaccines", "Viral Vector Vaccines", "Protein Subunit Vaccines",
    "Monoclonal Antibodies", "Antiviral Therapy", "Corticosteroids",
    "Convalescent Plasma", "Immunomodulators", "Remdesivir",
    "Tocilizumab", "Dexamethasone", "Hydroxychloroquine"
]

POPULATIONS = [
    "Healthcare Workers", "Elderly Patients", "Immunocompromised Individuals",
    "Pregnant Women", "Pediatric Patients", "Critical Care Patients",
    "Nursing Home Residents", "Frontline Workers", "High-Risk Groups"
]

STUDY_TYPES = [
    "Randomized Controlled Trial", "Systematic Review and Meta-Analysis",
    "Prospective Cohort Study", "Retrospective Analysis",
    "Cross-Sectional Study", "Case-Control Study", "Clinical Trial"
]

CONDITIONS = [
    "Acute Respiratory Distress Syndrome", "Severe COVID-19",
    "Post-COVID Syndrome", "Mild to Moderate COVID-19",
    "Asymptomatic SARS-CoV-2 Infection", "COVID-19 Pneumonia",
    "Coronavirus Disease 2019", "Long COVID"
]

OUTCOMES = [
    "Mortality Rates", "Hospital Admission Rates", "ICU Utilization",
    "Symptom Duration", "Viral Load Reduction", "Antibody Response",
    "Disease Progression", "Quality of Life"
]

VIRUSES = [
    "SARS-CoV-2", "Coronavirus", "Beta-Coronavirus", "Alpha Variant",
    "Delta Variant", "Omicron Variant"
]

PROCESSES = [
    "Replication", "Transmission", "Immune Evasion", "Pathogenesis",
    "Cellular Entry", "Spike Protein Binding"
]

INTERVENTIONS = [
    "Social Distancing", "Mask Mandates", "Lockdown Measures",
    "Vaccination Campaigns", "Contact Tracing", "Quarantine Protocols"
]

TESTS = [
    "RT-PCR Testing", "Rapid Antigen Tests", "Serological Assays",
    "Point-of-Care Diagnostics", "Chest CT Imaging", "Antibody Testing"
]

SPECIALTIES = [
    "Primary Care", "Respiratory Medicine", "Critical Care",
    "Infectious Diseases", "Geriatric Medicine", "Pediatrics"
]

AUTHORS = [
    "Smith J, Johnson M, Williams R",
    "Brown A, Davis K, Miller T",
    "Wilson S, Moore D, Taylor C",
    "Anderson L, Thomas E, Jackson H",
    "White N, Harris P, Martin G",
    "Thompson B, Garcia F, Martinez V",
    "Robinson W, Clark L, Rodriguez M"
]


def generate_metadata(doc_id: str) -> dict:
    """
    Generate realistic metadata for a document based on its ID.

    Uses deterministic hashing so the same doc_id always generates
    the same metadata.

    Args:
        doc_id: Document identifier (e.g., "PMC7326321")

    Returns:
        dict: {title, authors, abstract}
    """
    # Use hash of doc_id as seed for deterministic generation
    seed = int(hashlib.md5(doc_id.encode()).hexdigest()[:8], 16)

    # Select template and components based on seed
    template_idx = seed % len(TITLE_TEMPLATES)
    template = TITLE_TEMPLATES[template_idx]

    # Fill in template
    title = template.format(
        treatment=TREATMENTS[(seed >> 4) % len(TREATMENTS)],
        treatment_a=TREATMENTS[(seed >> 8) % len(TREATMENTS)],
        treatment_b=TREATMENTS[(seed >> 12) % len(TREATMENTS)],
        population=POPULATIONS[(seed >> 16) % len(POPULATIONS)],
        study_type=STUDY_TYPES[(seed >> 20) % len(STUDY_TYPES)],
        condition=CONDITIONS[(seed >> 24) % len(CONDITIONS)],
        intervention=INTERVENTIONS[(seed >> 28) % len(INTERVENTIONS)],
        outcome=OUTCOMES[(seed >> 32) % len(OUTCOMES)],
        virus=VIRUSES[(seed >> 36) % len(VIRUSES)],
        process=PROCESSES[(seed >> 40) % len(PROCESSES)],
        test=TESTS[(seed >> 44) % len(TESTS)],
        specialty=SPECIALTIES[(seed >> 48) % len(SPECIALTIES)]
    )

    # Generate authors
    author_list = AUTHORS[(seed >> 52) % len(AUTHORS)]

    # Generate abstract snippet
    abstracts = [
        f"This {STUDY_TYPES[(seed >> 20) % len(STUDY_TYPES)].lower()} investigates the {OUTCOMES[(seed >> 32) % len(OUTCOMES)].lower()} associated with {TREATMENTS[(seed >> 4) % len(TREATMENTS)].lower()}. We enrolled participants and followed standardized protocols to assess treatment efficacy and safety profiles.",

        f"Background: {CONDITIONS[(seed >> 24) % len(CONDITIONS)]} remains a significant clinical challenge. This study evaluates {TREATMENTS[(seed >> 4) % len(TREATMENTS)].lower()} as a potential therapeutic intervention in {POPULATIONS[(seed >> 16) % len(POPULATIONS)].lower()}.",

        f"Objectives: To determine the effectiveness of {INTERVENTIONS[(seed >> 28) % len(INTERVENTIONS)].lower()} in reducing {OUTCOMES[(seed >> 32) % len(OUTCOMES)].lower()} during the COVID-19 pandemic. Methods: We conducted a comprehensive analysis across multiple healthcare settings.",

        f"The emergence of {VIRUSES[(seed >> 36) % len(VIRUSES)]} has necessitated rapid development of diagnostic and therapeutic strategies. This review synthesizes current evidence on {TREATMENTS[(seed >> 4) % len(TREATMENTS)].lower()} and discusses implications for clinical practice."
    ]

    abstract = abstracts[seed % len(abstracts)]

    return {
        "title": title,
        "authors": author_list.split(", "),
        "abstract": abstract,
        "doc_id": doc_id
    }


def generate_metadata_database(doc_ids: list, output_path: str):
    """
    Generate metadata for a list of document IDs.

    Args:
        doc_ids: List of document IDs
        output_path: Path to save JSON file
    """
    metadata_db = {}

    for doc_id in doc_ids:
        metadata_db[doc_id] = generate_metadata(doc_id)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metadata_db, f, indent=2)

    print(f"Generated metadata for {len(doc_ids)} documents")
    print(f"Saved to: {output_path}")

    return metadata_db


def create_sample_metadata():
    """Create a sample metadata file with some example PMC IDs."""
    # Sample PMC IDs (these would come from your actual dataset)
    sample_ids = [
        "PMC7326321", "PMC7326322", "PMC7326323", "PMC7326324",
        "PMC8765432", "PMC8765433", "PMC8765434", "PMC8765435",
        "PMC9876543", "PMC9876544", "PMC9876545", "PMC9876546"
    ]

    backend_dir = Path(__file__).parent.parent
    indexes_dir = backend_dir / "indexes"
    indexes_dir.mkdir(exist_ok=True)

    output_path = indexes_dir / "document_metadata.json"

    generate_metadata_database(sample_ids, str(output_path))

    # Print sample
    print("\nSample metadata:")
    print("-" * 80)
    sample = generate_metadata("PMC7326321")
    print(f"Title: {sample['title']}")
    print(f"Authors: {', '.join(sample['authors'])}")
    print(f"Abstract: {sample['abstract'][:150]}...")


if __name__ == "__main__":
    create_sample_metadata()
