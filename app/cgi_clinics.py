import gzip
import logging
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

API_BASE_URL = os.getenv("CGI_CLINICS_API_BASE_URL", "https://platform.cgiclinics.eu/api/1.0")
PLATFORM_BASE_URL = API_BASE_URL.replace("/api/1.0", "")
CGI_CLINICS_PROJECT_UUID = os.getenv(
    "CGI_CLINICS_PROJECT_UUID",
    "73cc5dc0-d16d-4f12-a81e-103cb2cbfcfe",
)
CGI_CLINICS_API_KEY = os.getenv(
    "CGI_CLINICS_API_KEY",
    "80cd36a5-232b-4311-bd4b-5d3e70caf1cb#yzxAiZi-eU-vLywSCvv-ZvoCcgY",
)
CGI_CLINICS_API_TOKEN = os.getenv("CGI_CLINICS_API_TOKEN", CGI_CLINICS_API_KEY)

DEFAULT_PROJECT_UUID = CGI_CLINICS_PROJECT_UUID
DEFAULT_API_KEY = CGI_CLINICS_API_KEY or CGI_CLINICS_API_TOKEN
DEFAULT_SAMPLE_SOURCE = "PARAFFIN_EMBEDDED_TISSUE_FFPE"
DEFAULT_SEQUENCING_GERMLINE_CONTROL = "NO"
DEFAULT_REFERENCE_GENOME = "HG19"
DEFAULT_SEQUENCING_TYPE = "GenOncology-Dx"
CGI_EXCLUDED_FILTER_TAGS = {
    "base_qual",
    "orientation",
    "strand_bias",
    "weak_evidence",
    "slippage",
}
LUNG_CODE = "NSCLC"
DEFAULT_TUMOR_TYPE = LUNG_CODE

IGNORE_TERMS = {
    "TEIXITSA",
    "TEIXIT SA",
    "TEJIDO SANO",
    "HEALTHY TISSUE",
}

TUMOR_GROUPS = {
    LUNG_CODE: ["PULMO", "PULMON", "CANCER DE PULMO", "CANCER DE PULMON"],
    "BILIARY_TRACT": ["VIA BILIAR", "VIES BILIARS", "COLANGIOCARCINOMA", "PANCREATOBILIAR"],
    "PANCREAS": ["PANCREAS"],
    "LIVER": ["HEPATIC", "HEPATICO", "HEPATOCARCINOMA"],
    "COADREAD": ["COLON", "COLORRECTAL", "INTESTI", "INTESTINAL"],
    "STOMACH": ["ESTOMAC", "ESOFAG", "GASTRICO"],
    "THYROID": ["TIROIDES", "TIROIDES MEDULAR"],
    "PROSTATE": ["PROSTATA"],
    "BREAST": ["MAMA", "BREAST"],
    "UTERUS": ["UTER", "UTERO"],
    "UCEC": ["ENDOMETRI", "ENDOMETRIUM"],
    "BLADDER": ["UROTELIAL", "UROTHELIAL"],
    "BRAIN": ["CERVELL", "BRAIN", "CNS"],
    "SKIN": ["MELANOMA"],
    "SOFT_TISSUE": ["MIOFIBROBLASTIC", "SARCOMA"],
    "HEAD_NECK": ["GLANDULA SALIVAL", "SALIVAL"],
}


def _norm(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


IGNORE_TERMS_NORM = {_norm(term) for term in IGNORE_TERMS}


def _build_tumor_dict(groups: dict[str, list[str]]) -> dict[str, str]:
    tumor_dict: dict[str, str] = {}
    for code, terms in groups.items():
        for term in terms:
            normalized = _norm(term)
            if normalized:
                tumor_dict[normalized] = code
    return tumor_dict


TUMOR_DICT = _build_tumor_dict(TUMOR_GROUPS)


def _raise_for_status(response: requests.Response, action: str) -> None:
    if 200 <= response.status_code < 300:
        return
    raise requests.exceptions.HTTPError(
        f"{action} failed ({response.status_code}): {response.text}"
    )


def build_headers(api_key: str | None = None) -> dict[str, str]:
    token = api_key or DEFAULT_API_KEY
    if not token:
        raise ValueError("Missing CGI Clinics API key")
    return {"X-Api-Key": token}


def build_analysis_url(project_uuid: str | None, analysis_uuid: str | None) -> str:
    resolved_project_uuid = project_uuid or DEFAULT_PROJECT_UUID
    if not resolved_project_uuid or not analysis_uuid or analysis_uuid == ".":
        return ""
    return (
        f"{PLATFORM_BASE_URL}/analyses/project/"
        f"{resolved_project_uuid}/analysis/{analysis_uuid}/result"
    )


def build_analysis_name(
    run_id: str,
    lab_id: str,
    send_iteration: int | None = None,
    date_tag: str | None = None,
) -> str:
    resolved_date_tag = date_tag or datetime.now().strftime("%Y%m%d")
    base_name = f"{resolved_date_tag}_{run_id}_{lab_id}"
    if send_iteration and send_iteration > 1:
        return f"{base_name}_{send_iteration}"
    return base_name


def _is_analysis_id_exists_error(exc: Exception) -> bool:
    text = str(exc)
    return "analysis-id-already-exists" in text or "already exists" in text


def normalize_patient_age(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {".", "None"}:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def normalize_patient_sex(value: Any) -> str | None:
    text = _norm(value)
    if text in {"", ".", "NONE", "NULL"}:
        return None
    if text in {"HOME", "MALE", "M"}:
        return "MALE"
    if text in {"DONA", "FEMALE", "F"}:
        return "FEMALE"
    return text


def map_tumor_type_to_cgi(sample_or_text: dict[str, Any] | str | None) -> str | None:
    if isinstance(sample_or_text, dict):
        tumor_origin = sample_or_text.get("tumor_origin")
        diagnosis = sample_or_text.get("diagnosis") or ""
        raw = f"{tumor_origin or ''} {diagnosis}".strip()
    else:
        raw = str(sample_or_text or "")

    key = _norm(raw)
    if key in {"", "NONE", "NULL", "."}:
        return None
    if key in IGNORE_TERMS_NORM:
        return None
    if "TEIXIT SA" in key or "TEIXITSA" in key or "TEJIDO SANO" in key:
        return None
    if key in TUMOR_DICT:
        return TUMOR_DICT[key]
    if "PULMO" in key or "PULMON" in key or "PULMONAR" in key:
        return LUNG_CODE
    if "COLANGIO" in key or "BILI" in key:
        return "BILIARY_TRACT"
    if "PANCRE" in key:
        return "PANCREAS"
    if "HEPAT" in key or "FETGE" in key:
        return "LIVER"
    if "COLON" in key or "INTEST" in key:
        return "COADREAD"
    if "ESTOMAC" in key or "ESOFAG" in key or "GASTR" in key:
        return "STOMACH"
    if "TIROID" in key:
        return "THYROID"
    if "PROSTAT" in key:
        return "PROSTATE"
    if "MELANOM" in key:
        return "SKIN"
    if "ENDOMET" in key:
        return "UCEC"
    if "UROTEL" in key:
        return "BLADDER"
    if "CERVELL" in key or "BRAIN" in key or "CNS" in key:
        return "BRAIN"
    if "MAMA" in key or "BREAST" in key:
        return "BREAST"
    if "SALIVAL" in key:
        return "HEAD_NECK"
    if "MIOFIBROBL" in key or "SARCOMA" in key:
        return "SOFT_TISSUE"
    return None


def _build_cgi_filtered_vcf(source_vcf: Path, sample_id: str) -> tuple[Path, int]:
    if not source_vcf.is_file():
        raise FileNotFoundError(f"VCF file not found: {source_vcf}")

    is_gzipped_input = str(source_vcf).endswith((".gz", ".bgz"))
    input_open = gzip.open if is_gzipped_input else open
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".cgi.filtered.vcf",
        prefix=f"{sample_id}.",
        dir=str(source_vcf.parent),
        delete=False,
    ) as out_fh:
        filtered_path = Path(out_fh.name)
        kept_records = 0

        with input_open(source_vcf, "rt") as in_fh:
            for line in in_fh:
                if line.startswith("#"):
                    out_fh.write(line)
                    continue

                parts = line.rstrip("\n").split("\t")
                if len(parts) < 8:
                    continue

                filter_field = parts[6]
                filter_tags = set()
                for raw_tag in re.split(r"[;,]", filter_field):
                    cleaned_tag = raw_tag.strip().lower()
                    if cleaned_tag and cleaned_tag != ".":
                        filter_tags.add(cleaned_tag)
                if filter_tags.intersection(CGI_EXCLUDED_FILTER_TAGS):
                    continue

                ref = parts[3].strip().upper()
                alt_field = parts[4].strip().upper()
                alt_alleles = [alt.strip() for alt in alt_field.split(",") if alt.strip()]
                if not alt_alleles:
                    continue

                unsupported_alt = False
                for alt in alt_alleles:
                    if any(ch in alt for ch in "[]<>") or alt.startswith(".") or alt.endswith("."):
                        unsupported_alt = True
                        break
                    if not re.fullmatch(r"[ACGTN]+", ref) or not re.fullmatch(r"[ACGTN]+", alt):
                        unsupported_alt = True
                        break
                    if len(ref) != len(alt):
                        unsupported_alt = True
                        break
                if unsupported_alt:
                    continue

                out_fh.write(line)
                kept_records += 1

    return filtered_path, kept_records


def request_temporal_upload(project_uuid: str, main_headers: dict[str, str]) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}/project/{project_uuid}/temporal-upload",
        headers=main_headers,
        timeout=60,
        json={"type": "ANALYSIS_INPUT"},
    )
    _raise_for_status(response, "Temporal upload request")
    return response.json()


def upload_file_to_temporal(
    project_uuid: str,
    file_path: Path,
    upload_request: dict[str, Any],
    main_headers: dict[str, str],
) -> str:
    if "uuid" not in upload_request or "code" not in upload_request:
        raise ValueError("Invalid upload request")
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    upload_body = {"type": "ANALYSIS_INPUT", "code": upload_request["code"]}
    with open(file_path, "rb") as handle:
        response = requests.post(
            f"{API_BASE_URL}/public/project/{project_uuid}/temporal-upload/{upload_request['uuid']}",
            headers=main_headers,
            timeout=120,
            data=upload_body,
            files={"file": handle},
        )
    _raise_for_status(response, "Temporal upload")
    payload = response.json()
    return payload["uuid"]


def upload_file(project_uuid: str, file_path: Path, main_headers: dict[str, str]) -> str:
    upload_request = request_temporal_upload(project_uuid, main_headers)
    return upload_file_to_temporal(project_uuid, file_path, upload_request, main_headers)


def create_direct_analysis(
    project_uuid: str,
    main_headers: dict[str, str],
    patient_id: str,
    sample_id: str,
    sequencing_id: str,
    analysis_id: str,
    sample_source: str,
    tumor_type: str,
    sequencing_type: str,
    reference_genome: str,
    sequencing_germline_control: str,
    informed_consent: bool,
    non_consent_reason: str | None = None,
    sequencing_type_other: str | None = None,
    input_files: list[Path] | None = None,
    input_text: str | None = None,
    input_format: str | None = None,
) -> dict[str, Any]:
    if input_files is None and input_text is None:
        raise ValueError("Either input_files or input_text must be provided")
    if input_files is not None and input_text is not None:
        raise ValueError("Cannot use both input_files and input_text together")
    if input_text is not None and input_format is None:
        raise ValueError("Format must be specified when using input_text")
    if not informed_consent and not non_consent_reason:
        raise ValueError("non_consent_reason is required when informed_consent is False")
    if informed_consent and non_consent_reason:
        raise ValueError("non_consent_reason must be empty when informed_consent is True")

    request_body: dict[str, Any] = {
        "patientId": patient_id,
        "sampleId": sample_id,
        "sequencingId": sequencing_id,
        "analysisId": analysis_id,
        "sampleSource": sample_source,
        "tumorType": tumor_type,
        "sequencingType": sequencing_type,
        "referenceGenome": reference_genome,
        "sequencingGermlineControl": sequencing_germline_control,
        "informedConsent": informed_consent,
        "nonConsentReason": non_consent_reason,
    }
    if sequencing_type_other is not None:
        request_body["sequencingTypeOther"] = sequencing_type_other
    if input_files is not None:
        input_file_ids = []
        for file_path in input_files:
            input_file_ids.append(upload_file(project_uuid, file_path, main_headers))
        request_body["inputFiles"] = input_file_ids
    else:
        request_body["inputText"] = input_text
        request_body["format"] = input_format

    response = requests.post(
        f"{API_BASE_URL}/project/{project_uuid}/direct-analysis",
        headers=main_headers,
        timeout=60,
        json=request_body,
    )
    _raise_for_status(response, "Create direct analysis")
    return response.json()


def get_all_samples_paginated(
    project_uuid: str,
    main_headers: dict[str, str],
    patient_uuid: str | None = None,
    size: int = 2000,
    page: int = 0,
) -> dict[str, Any]:
    if size > 2000:
        raise ValueError("Maximum CGI page size is 2000")
    params = {
        "projectUuid": project_uuid,
        "patientUuid": patient_uuid,
        "size": size,
        "page": page,
    }
    response = requests.get(
        f"{API_BASE_URL}/project/{project_uuid}/sample",
        headers=main_headers,
        timeout=60,
        params=params,
    )
    _raise_for_status(response, "Get paginated samples")
    return response.json()


def get_sample_by_uuid(
    project_uuid: str,
    sample_uuid: str,
    main_headers: dict[str, str],
) -> dict[str, Any]:
    response = requests.get(
        f"{API_BASE_URL}/project/{project_uuid}/sample/{sample_uuid}",
        headers=main_headers,
        timeout=60,
    )
    _raise_for_status(response, "Get sample by UUID")
    return response.json()


def update_sample(
    project_uuid: str,
    sample_uuid: str,
    main_headers: dict[str, str],
    patient_uuid: str | None = None,
    sample_id: str | None = None,
    sex: str | None = None,
    source: str | None = None,
    tumor_type: str | None = None,
    tumor_sub_type: str | None = None,
    purity: int | None = None,
    type: str | None = None,
    metastatic_site: str | None = None,
    age_at_sampling: int | None = None,
    informed_consent_notes: str | None = None,
    share_for_research: bool | None = None,
    date: str | None = None,
    biomarkers: list[dict[str, Any]] | None = None,
    informed_consent: bool | None = None,
    non_consent_reason: str | None = None,
) -> dict[str, Any]:
    body = {
        "patientUuid": patient_uuid,
        "sampleId": sample_id,
        "sex": sex,
        "source": source,
        "tumorType": tumor_type,
        "tumorSubType": tumor_sub_type,
        "purity": purity,
        "type": type,
        "metastaticSite": metastatic_site,
        "ageAtSampling": age_at_sampling,
        "informedConsentNotes": informed_consent_notes,
        "shareForResearch": share_for_research,
        "date": date,
        "biomarkers": biomarkers,
        "informedConsent": informed_consent,
        "nonConsentReason": non_consent_reason,
    }
    response = requests.put(
        f"{API_BASE_URL}/project/{project_uuid}/sample/{sample_uuid}",
        headers=main_headers,
        json=body,
        timeout=60,
    )
    _raise_for_status(response, "Update sample")
    return response.json()


def _extract_existing_sample_update_fields(sample_payload: dict[str, Any]) -> dict[str, Any]:
    patient_obj = sample_payload.get("patient")
    patient_uuid = sample_payload.get("patientUuid")
    if not patient_uuid and isinstance(patient_obj, dict):
        patient_uuid = patient_obj.get("uuid") or patient_obj.get("patientUuid")

    informed_consent = sample_payload.get("informedConsent")
    if informed_consent is None and isinstance(patient_obj, dict):
        informed_consent = patient_obj.get("informedConsent")

    existing = {
        "patient_uuid": patient_uuid,
        "sample_id": sample_payload.get("sampleId"),
        "source": sample_payload.get("source") or sample_payload.get("sampleSource"),
        "tumor_type": sample_payload.get("tumorType"),
        "tumor_sub_type": sample_payload.get("tumorSubType"),
        "purity": sample_payload.get("purity"),
        "type": sample_payload.get("type"),
        "metastatic_site": sample_payload.get("metastaticSite"),
        "age_at_sampling": sample_payload.get("ageAtSampling"),
        "informed_consent_notes": sample_payload.get("informedConsentNotes"),
        "share_for_research": sample_payload.get("shareForResearch"),
        "date": sample_payload.get("date"),
        "biomarkers": sample_payload.get("biomarkers"),
        "informed_consent": informed_consent,
        "non_consent_reason": sample_payload.get("nonConsentReason"),
    }
    return existing


def _extract_sample_uuid(analysis_result: dict[str, Any]) -> str | None:
    for key in ("sampleUuid", "sample_uuid", "sampleUUID"):
        if analysis_result.get(key):
            return analysis_result.get(key)
    sample_obj = analysis_result.get("sample")
    if isinstance(sample_obj, dict):
        for key in ("uuid", "sampleUuid", "sampleUUID"):
            if sample_obj.get(key):
                return sample_obj.get(key)
    return None


def _find_sample_uuid_by_sample_id(
    project_uuid: str,
    sample_id: str,
    headers: dict[str, str],
    page_size: int = 2000,
    max_pages: int = 5,
) -> str | None:
    for page in range(max_pages):
        payload = get_all_samples_paginated(
            project_uuid=project_uuid,
            main_headers=headers,
            size=page_size,
            page=page,
        )
        items = None
        if isinstance(payload, dict):
            for key in ("items", "records", "data", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    items = value
                    break
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("sampleId")) == str(sample_id):
                return item.get("uuid") or item.get("sampleUuid")
    return None


def create_direct_analysis_from_vcf(
    final_vcf: str | Path,
    run_id: str,
    lab_id: str,
    sequencing_type: str = DEFAULT_SEQUENCING_TYPE,
    tumor_type: str | None = None,
    tumor_origin: str | None = None,
    diagnosis: str | None = None,
    project_uuid: str | None = None,
    api_key: str | None = None,
    sample_source: str = DEFAULT_SAMPLE_SOURCE,
    reference_genome: str = DEFAULT_REFERENCE_GENOME,
    sequencing_germline_control: str = DEFAULT_SEQUENCING_GERMLINE_CONTROL,
    informed_consent: bool = False,
    non_consent_reason: str = "Not available",
    update_sample_metadata: bool = False,
    patient_age: Any = None,
    patient_sex: Any = None,
    send_iteration: int | None = None,
) -> dict[str, Any]:
    vcf_path = Path(final_vcf)
    if not vcf_path.is_file():
        raise FileNotFoundError(f"VCF file not found: {vcf_path}")
    if not run_id:
        raise ValueError("run_id is required for CGI direct analysis")
    if not lab_id:
        raise ValueError("lab_id is required for CGI direct analysis")
    if not sequencing_type:
        raise ValueError("sequencing_type is required for CGI direct analysis")

    resolved_project_uuid = project_uuid or DEFAULT_PROJECT_UUID
    if not resolved_project_uuid:
        raise ValueError("Missing CGI project UUID")

    headers = build_headers(api_key)
    if not tumor_type:
        tumor_type = map_tumor_type_to_cgi(
            {"tumor_origin": tumor_origin, "diagnosis": diagnosis}
        )
    if not tumor_type:
        tumor_type = DEFAULT_TUMOR_TYPE
        logging.warning(
            "CGI tumor type could not be mapped for sample %s. Using default %s.",
            lab_id,
            tumor_type,
        )

    date_tag = datetime.now().strftime("%Y%m%d")
    patient_id = lab_id
    sample_id = lab_id
    filtered_vcf_path, kept_records = _build_cgi_filtered_vcf(vcf_path, lab_id)
    if kept_records == 0:
        if filtered_vcf_path.exists():
            filtered_vcf_path.unlink()
        raise ValueError(f"No variants available for CGI after filtering sample {lab_id}.")

    start_iteration = send_iteration or 1
    used_send_iteration = start_iteration
    analysis_name = build_analysis_name(
        run_id=run_id,
        lab_id=lab_id,
        send_iteration=used_send_iteration,
        date_tag=date_tag,
    )
    last_error = None
    result = None
    try:
        for attempt in range(10):
            used_send_iteration = start_iteration + attempt
            analysis_name = build_analysis_name(
                run_id=run_id,
                lab_id=lab_id,
                send_iteration=used_send_iteration,
                date_tag=date_tag,
            )
            try:
                result = create_direct_analysis(
                    project_uuid=resolved_project_uuid,
                    main_headers=headers,
                    patient_id=patient_id,
                    sample_id=sample_id,
                    sequencing_id=analysis_name,
                    analysis_id=analysis_name,
                    sample_source=sample_source,
                    tumor_type=tumor_type,
                    sequencing_type=sequencing_type,
                    reference_genome=reference_genome,
                    sequencing_germline_control=sequencing_germline_control,
                    informed_consent=informed_consent,
                    non_consent_reason=non_consent_reason,
                    input_files=[filtered_vcf_path],
                )
                break
            except requests.exceptions.HTTPError as exc:
                last_error = exc
                if _is_analysis_id_exists_error(exc):
                    logging.warning(
                        "CGI analysis id %s already exists for sample %s. Retrying with next suffix.",
                        analysis_name,
                        lab_id,
                    )
                    continue
                raise
        if result is None:
            raise last_error or RuntimeError(
                f"Could not create a unique CGI analysis id for sample {lab_id}."
            )
    finally:
        if filtered_vcf_path.exists():
            filtered_vcf_path.unlink()

    normalized_age = normalize_patient_age(patient_age)
    normalized_sex = normalize_patient_sex(patient_sex)
    if update_sample_metadata and (normalized_age is not None or normalized_sex is not None):
        sample_uuid = _extract_sample_uuid(result) or _find_sample_uuid_by_sample_id(
            project_uuid=resolved_project_uuid,
            sample_id=sample_id,
            headers=headers,
        )
        if sample_uuid:
            try:
                existing_sample_payload = get_sample_by_uuid(
                    project_uuid=resolved_project_uuid,
                    sample_uuid=sample_uuid,
                    main_headers=headers,
                )
                update_kwargs = _extract_existing_sample_update_fields(existing_sample_payload)
                update_kwargs["age_at_sampling"] = normalized_age
                update_kwargs["sex"] = normalized_sex
                update_sample(
                    project_uuid=resolved_project_uuid,
                    sample_uuid=sample_uuid,
                    main_headers=headers,
                    **update_kwargs,
                )
            except Exception as exc:
                logging.warning(
                    "Could not update CGI sample metadata for %s: %s",
                    sample_id,
                    exc,
                )
                if isinstance(result, dict):
                    result["_metadata_update_warning"] = str(exc)
        else:
            logging.warning(
                "Could not resolve CGI sample UUID for metadata update on sample %s.",
                sample_id,
            )

    if isinstance(result, dict):
        result["_kept_records"] = kept_records
        result["_tumor_type"] = tumor_type
        result["_vcf_path"] = str(vcf_path)
        result["_project_uuid"] = resolved_project_uuid
        result["_analysis_url"] = build_analysis_url(
            resolved_project_uuid,
            result.get("uuid") or result.get("analysisUuid") or result.get("analysis_uuid"),
        )
        result["_analysis_name"] = analysis_name
        result["_send_iteration"] = used_send_iteration
    return result
