import json
import os
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types


def _build_system_prompt(job_description: str, weights: dict[str, int], role_titles: list[str], is_batch: bool = False) -> str:
    weights_json = json.dumps(weights, ensure_ascii=False)
    titles = ", ".join(role_titles) if role_titles else "N/A"
    
    if is_batch:
        return (
            "Você é um recrutador técnico. Analise os PDFs dos candidatos (múltiplos arquivos) com base nesta DESCRIÇÃO DA VAGA.\n\n"
            "IMPORTANTE: Todas as respostas devem ser em PORTUGUÊS (Brasil). Campos de texto, justificativas e valores devem estar em português.\n\n"
            f"DESCRIÇÃO DA VAGA:\n{job_description}\n\n"
            f"TÍTULOS DA VAGA (variações PT/EN): {titles}\n\n"
            "Calcule a aderência de 0 a 100% seguindo os pesos abaixo:\n"
            f"{weights_json}\n\n"
            "Regras:\n"
            "- Retorne apenas JSON válido (sem markdown).\n"
            "- Retorne um ARRAY de objetos, um para cada PDF enviado, na mesma ordem.\n"
            "- Se não encontrar um campo, retorne null ou lista vazia.\n"
            "- Skills/tecnologias/idiomas/certificações devem ser listas.\n"
            "- Média de permanência e tempo de experiência devem ser em ANOS (decimal).\n"
            "- Senioridade deve seguir:\n"
            "  0 a 1 ano: Trainee; 1 a 2 anos: Junior; 2 a 5 anos: Pleno; 5 a 8 anos: Senior; 8+ anos: Especialista.\n"
            "- Justificativa técnica deve ser UMA FRASE CURTA (máximo 150 caracteres) resumindo os principais pontos de aderência.\n\n"
            "Retorne exatamente no formato (ARRAY):\n"
            "[\n"
            "  {\n"
            '    "name": "string",\n'
            '    "linkedin_url": "string",\n'
            '    "location": "string",\n'
            '    "current_title": "string",\n'
            '    "current_company": "string",\n'
            '    "skills": ["string"],\n'
            '    "technologies": ["string"],\n'
            '    "languages": ["string"],\n'
            '    "certifications": ["string"],\n'
            '    "average_tenure_years": 0.0,\n'
            '    "experience_time_years": 0.0,\n'
            '    "seniority": "string",\n'
            '    "adherence": 0,\n'
            '    "technical_justification": "string"\n'
            "  }\n"
            "]\n"
        )
    else:
        return (
            "Você é um recrutador técnico. Analise o PDF do candidato com base nesta DESCRIÇÃO DA VAGA.\n\n"
            "IMPORTANTE: Todas as respostas devem ser em PORTUGUÊS (Brasil). Campos de texto, justificativas e valores devem estar em português.\n\n"
            f"DESCRIÇÃO DA VAGA:\n{job_description}\n\n"
            f"TÍTULOS DA VAGA (variações PT/EN): {titles}\n\n"
            "Calcule a aderência de 0 a 100% seguindo os pesos abaixo:\n"
            f"{weights_json}\n\n"
            "Regras:\n"
            "- Retorne apenas JSON válido (sem markdown).\n"
            "- Se não encontrar um campo, retorne null ou lista vazia.\n"
            "- Skills/tecnologias/idiomas/certificações devem ser listas.\n"
            "- Média de permanência e tempo de experiência devem ser em ANOS (decimal).\n"
            "- Senioridade deve seguir:\n"
            "  0 a 1 ano: Trainee; 1 a 2 anos: Junior; 2 a 5 anos: Pleno; 5 a 8 anos: Senior; 8+ anos: Especialista.\n"
            "- Justificativa técnica deve ser UMA FRASE CURTA (máximo 150 caracteres) resumindo os principais pontos de aderência.\n\n"
            "Retorne exatamente no formato:\n"
            "{\n"
            '  "name": "string",\n'
            '  "linkedin_url": "string",\n'
            '  "location": "string",\n'
            '  "current_title": "string",\n'
            '  "current_company": "string",\n'
            '  "skills": ["string"],\n'
            '  "technologies": ["string"],\n'
            '  "languages": ["string"],\n'
            '  "certifications": ["string"],\n'
            '  "average_tenure_years": 0.0,\n'
            '  "experience_time_years": 0.0,\n'
            '  "seniority": "string",\n'
            '  "adherence": 0,\n'
            '  "technical_justification": "string"\n'
            "}\n"
        )


def _build_system_prompt_no_ranking(is_batch: bool = False) -> str:
    """Constrói prompt para extração sem rankeamento (para banco de talentos)."""
    if is_batch:
        return (
            "Você é um recrutador técnico. Analise os PDFs dos candidatos (múltiplos arquivos) e extraia as informações.\n\n"
            "IMPORTANTE: Todas as respostas devem ser em PORTUGUÊS (Brasil). Campos de texto e valores devem estar em português.\n\n"
            "Regras:\n"
            "- Retorne apenas JSON válido (sem markdown).\n"
            "- Retorne um ARRAY de objetos, um para cada PDF enviado, na mesma ordem.\n"
            "- Se não encontrar um campo, retorne null ou lista vazia.\n"
            "- Skills/tecnologias/idiomas/certificações devem ser listas.\n"
            "- Média de permanência e tempo de experiência devem ser em ANOS (decimal).\n"
            "- Senioridade deve seguir:\n"
            "  0 a 1 ano: Trainee; 1 a 2 anos: Junior; 2 a 5 anos: Pleno; 5 a 8 anos: Senior; 8+ anos: Especialista.\n"
            "- Se não encontrar o cargo específico nas experiências, experience_time_years deve ser null.\n\n"
            "Retorne exatamente no formato (ARRAY):\n"
            "[\n"
            "  {\n"
            '    "name": "string",\n'
            '    "linkedin_url": "string",\n'
            '    "location": "string",\n'
            '    "current_title": "string",\n'
            '    "current_company": "string",\n'
            '    "skills": ["string"],\n'
            '    "technologies": ["string"],\n'
            '    "languages": ["string"],\n'
            '    "certifications": ["string"],\n'
            '    "average_tenure_years": 0.0,\n'
            '    "experience_time_years": 0.0,\n'
            '    "seniority": "string"\n'
            "  }\n"
            "]\n"
        )
    else:
        return (
            "Você é um recrutador técnico. Analise o PDF do candidato e extraia as informações.\n\n"
            "IMPORTANTE: Todas as respostas devem ser em PORTUGUÊS (Brasil). Campos de texto e valores devem estar em português.\n\n"
            "Regras:\n"
            "- Retorne apenas JSON válido (sem markdown).\n"
            "- Se não encontrar um campo, retorne null ou lista vazia.\n"
            "- Skills/tecnologias/idiomas/certificações devem ser listas.\n"
            "- Média de permanência e tempo de experiência devem ser em ANOS (decimal).\n"
            "- Senioridade deve seguir:\n"
            "  0 a 1 ano: Trainee; 1 a 2 anos: Junior; 2 a 5 anos: Pleno; 5 a 8 anos: Senior; 8+ anos: Especialista.\n"
            "- Se não encontrar o cargo específico nas experiências, experience_time_years deve ser null.\n\n"
            "Retorne exatamente no formato:\n"
            "{\n"
            '  "name": "string",\n'
            '  "linkedin_url": "string",\n'
            '  "location": "string",\n'
            '  "current_title": "string",\n'
            '  "current_company": "string",\n'
            '  "skills": ["string"],\n'
            '  "technologies": ["string"],\n'
            '  "languages": ["string"],\n'
            '  "certifications": ["string"],\n'
            '  "average_tenure_years": 0.0,\n'
            '  "experience_time_years": 0.0,\n'
            '  "seniority": "string"\n'
            "}\n"
        )


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()]


def _normalize_linkedin_url(value: str) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    if "linkedin.com" not in trimmed:
        return trimmed
    if not trimmed.startswith("http"):
        return f"https://{trimmed.lstrip('/')}"
    return trimmed


def _extract_json(text: str) -> dict | list:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Tenta encontrar array primeiro
        array_start = text.find("[")
        array_end = text.rfind("]")
        if array_start != -1 and array_end != -1 and array_end > array_start:
            try:
                return json.loads(text[array_start : array_end + 1])
            except json.JSONDecodeError:
                pass
        # Tenta encontrar objeto
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def extract_candidates_batch_with_llm(
    pdf_paths: list[str | Path],
    job_description: str,
    weights: dict[str, int],
    role_titles: list[str] | None = None,
) -> list[dict]:
    """Processa múltiplos PDFs em uma única requisição ao LLM."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não definido no ambiente.")

    system_prompt = _build_system_prompt(job_description, weights, role_titles or [], is_batch=True)
    client = genai.Client(api_key=api_key)

    payload = []
    for pdf_path in pdf_paths:
        with open(pdf_path, "rb") as pdf_file:
            payload.append(types.Part.from_bytes(data=pdf_file.read(), mime_type="application/pdf"))
    payload.append(system_prompt)

    last_error = None
    model_candidates = ["models/gemini-2.0-flash"]
    backoff_seconds = [3, 8, 15, 30]
    for attempt in range(4):
        for model_name in model_candidates:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=payload,
                )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if not last_error:
            break
        error_str = str(last_error)
        if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
            wait_time = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            time.sleep(wait_time)
        elif "503" in error_str or "UNAVAILABLE" in error_str:
            time.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
        else:
            time.sleep(3)
    if last_error:
        raise last_error

    data = _extract_json(response.text)
    
    # Garante que é uma lista
    if not isinstance(data, list):
        data = [data]
    
    # Valida que temos o mesmo número de resultados que PDFs enviados
    if len(data) != len(pdf_paths):
        raise RuntimeError(
            f"O LLM retornou {len(data)} resultado(s), mas foram enviados {len(pdf_paths)} PDF(s). "
            "Tente novamente ou processe em lotes menores."
        )
    
    results = []
    for item in data:
        results.append({
            "name": item.get("name") or "",
            "linkedin_url": _normalize_linkedin_url(item.get("linkedin_url") or ""),
            "location": item.get("location") or "",
            "current_title": item.get("current_title") or "",
            "current_company": item.get("current_company") or "",
            "skills": _normalize_list(item.get("skills")),
            "technologies": _normalize_list(item.get("technologies")),
            "languages": _normalize_list(item.get("languages")),
            "certifications": _normalize_list(item.get("certifications")),
            "average_tenure_years": item.get("average_tenure_years"),
            "experience_time_years": item.get("experience_time_years"),
            "seniority": item.get("seniority") or "",
            "adherence": item.get("adherence"),
            "technical_justification": item.get("technical_justification") or "",
        })
    
    return results


def extract_candidate_with_llm(
    pdf_path: str | Path,
    job_description: str,
    weights: dict[str, int],
    role_titles: list[str] | None = None,
) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não definido no ambiente.")

    system_prompt = _build_system_prompt(job_description, weights, role_titles or [], is_batch=False)
    client = genai.Client(api_key=api_key)

    with open(pdf_path, "rb") as pdf_file:
        payload = [
            types.Part.from_bytes(data=pdf_file.read(), mime_type="application/pdf"),
            system_prompt,
        ]
        last_error = None
        model_candidates = [
            "models/gemini-2.0-flash",
        ]
        backoff_seconds = [3, 8, 15, 30]
        for attempt in range(4):
            for model_name in model_candidates:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=payload,
                    )
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
            if not last_error:
                break
            error_str = str(last_error)
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                wait_time = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                time.sleep(wait_time)
            elif "503" in error_str or "UNAVAILABLE" in error_str:
                time.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
            else:
                time.sleep(3)
        if last_error:
            raise last_error
    data = _extract_json(response.text)

    return {
        "name": data.get("name") or "",
        "linkedin_url": _normalize_linkedin_url(data.get("linkedin_url") or ""),
        "location": data.get("location") or "",
        "current_title": data.get("current_title") or "",
        "current_company": data.get("current_company") or "",
        "skills": _normalize_list(data.get("skills")),
        "technologies": _normalize_list(data.get("technologies")),
        "languages": _normalize_list(data.get("languages")),
        "certifications": _normalize_list(data.get("certifications")),
        "average_tenure_years": data.get("average_tenure_years"),
        "experience_time_years": data.get("experience_time_years"),
        "seniority": data.get("seniority") or "",
        "adherence": data.get("adherence"),
        "technical_justification": data.get("technical_justification") or "",
    }


def extract_candidates_batch_no_ranking(
    pdf_paths: list[str | Path],
) -> list[dict]:
    """Processa múltiplos PDFs em uma única requisição ao LLM sem rankeamento."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não definido no ambiente.")

    system_prompt = _build_system_prompt_no_ranking(is_batch=True)
    client = genai.Client(api_key=api_key)

    payload = []
    for pdf_path in pdf_paths:
        with open(pdf_path, "rb") as pdf_file:
            payload.append(types.Part.from_bytes(data=pdf_file.read(), mime_type="application/pdf"))
    payload.append(system_prompt)

    last_error = None
    model_candidates = ["models/gemini-2.0-flash"]
    backoff_seconds = [3, 8, 15, 30]
    for attempt in range(4):
        for model_name in model_candidates:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=payload,
                )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if not last_error:
            break
        error_str = str(last_error)
        if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
            wait_time = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            time.sleep(wait_time)
        elif "503" in error_str or "UNAVAILABLE" in error_str:
            time.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
        else:
            time.sleep(3)
    if last_error:
        raise last_error

    data = _extract_json(response.text)
    
    # Garante que é uma lista
    if not isinstance(data, list):
        data = [data]
    
    # Valida que temos o mesmo número de resultados que PDFs enviados
    if len(data) != len(pdf_paths):
        raise RuntimeError(
            f"O LLM retornou {len(data)} resultado(s), mas foram enviados {len(pdf_paths)} PDF(s). "
            "Tente novamente ou processe em lotes menores."
        )
    
    results = []
    for item in data:
        results.append({
            "name": item.get("name") or "",
            "linkedin_url": _normalize_linkedin_url(item.get("linkedin_url") or ""),
            "location": item.get("location") or "",
            "current_title": item.get("current_title") or "",
            "current_company": item.get("current_company") or "",
            "skills": _normalize_list(item.get("skills")),
            "technologies": _normalize_list(item.get("technologies")),
            "languages": _normalize_list(item.get("languages")),
            "certifications": _normalize_list(item.get("certifications")),
            "average_tenure_years": item.get("average_tenure_years"),
            "experience_time_years": item.get("experience_time_years"),
            "seniority": item.get("seniority") or "",
        })
    
    return results


def calculate_adherence_for_candidate(
    candidate_data: dict,
    job_description: str,
    weights: dict[str, int],
    role_titles: list[str] | None = None,
) -> dict:
    """Calcula aderência e justificativa para um candidato já no banco."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não definido no ambiente.")

    weights_json = json.dumps(weights, ensure_ascii=False)
    titles = ", ".join(role_titles) if role_titles else "N/A"
    
    # Constrói texto com dados do candidato
    candidate_text = (
        f"Nome: {candidate_data.get('name', '')}\n"
        f"Cargo atual: {candidate_data.get('current_title', '')}\n"
        f"Empresa atual: {candidate_data.get('current_company', '')}\n"
        f"Localização: {candidate_data.get('location', '')}\n"
        f"Skills: {candidate_data.get('skills', '')}\n"
        f"Tecnologias: {candidate_data.get('technologies', '')}\n"
        f"Idiomas: {candidate_data.get('languages', '')}\n"
        f"Certificações: {candidate_data.get('certifications', '')}\n"
        f"Senioridade: {candidate_data.get('seniority', '')}\n"
        f"Tempo de experiência: {candidate_data.get('experience_time', '')} anos\n"
        f"Média de permanência: {candidate_data.get('average_tenure', '')} anos\n"
        f"Resumo: {candidate_data.get('summary', '')}\n"
    )
    
    system_prompt = (
        "Você é um recrutador técnico. Analise o perfil do candidato abaixo com base nesta DESCRIÇÃO DA VAGA.\n\n"
        "IMPORTANTE: Todas as respostas devem ser em PORTUGUÊS (Brasil). Campos de texto, justificativas e valores devem estar em português.\n\n"
        f"DESCRIÇÃO DA VAGA:\n{job_description}\n\n"
        f"TÍTULOS DA VAGA (variações PT/EN): {titles}\n\n"
        "Calcule a aderência de 0 a 100% seguindo os pesos abaixo:\n"
        f"{weights_json}\n\n"
        "PERFIL DO CANDIDATO:\n"
        f"{candidate_text}\n\n"
        "Regras:\n"
        "- Retorne apenas JSON válido (sem markdown).\n"
        "- Justificativa técnica deve ser UMA FRASE CURTA (máximo 150 caracteres) resumindo os principais pontos de aderência.\n\n"
        "Retorne exatamente no formato:\n"
        "{\n"
        '  "adherence": 0,\n'
        '  "technical_justification": "string"\n'
        "}\n"
    )
    
    client = genai.Client(api_key=api_key)
    payload = [system_prompt]
    
    last_error = None
    model_candidates = ["models/gemini-2.0-flash"]
    backoff_seconds = [3, 8, 15, 30]
    for attempt in range(4):
        for model_name in model_candidates:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=payload,
                )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if not last_error:
            break
        error_str = str(last_error)
        if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
            wait_time = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            time.sleep(wait_time)
        elif "503" in error_str or "UNAVAILABLE" in error_str:
            time.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
        else:
            time.sleep(3)
    if last_error:
        raise last_error
    
    data = _extract_json(response.text)
    
    return {
        "adherence": data.get("adherence"),
        "technical_justification": data.get("technical_justification") or "",
    }


def calculate_adherence_batch_for_candidates(
    candidates_data: list[dict],
    job_description: str,
    weights: dict[str, int],
    role_titles: list[str] | None = None,
) -> list[dict]:
    """Calcula aderência e justificativa para múltiplos candidatos em lote."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não definido no ambiente.")

    weights_json = json.dumps(weights, ensure_ascii=False)
    titles = ", ".join(role_titles) if role_titles else "N/A"
    
    # Constrói texto com dados de todos os candidatos
    candidates_text = ""
    for idx, candidate_data in enumerate(candidates_data):
        candidates_text += (
            f"\n--- CANDIDATO {idx + 1} ---\n"
            f"Nome: {candidate_data.get('name', '')}\n"
            f"Cargo atual: {candidate_data.get('current_title', '')}\n"
            f"Empresa atual: {candidate_data.get('current_company', '')}\n"
            f"Localização: {candidate_data.get('location', '')}\n"
            f"Skills: {candidate_data.get('skills', '')}\n"
            f"Tecnologias: {candidate_data.get('technologies', '')}\n"
            f"Idiomas: {candidate_data.get('languages', '')}\n"
            f"Certificações: {candidate_data.get('certifications', '')}\n"
            f"Senioridade: {candidate_data.get('seniority', '')}\n"
            f"Tempo de experiência: {candidate_data.get('experience_time', '')} anos\n"
            f"Média de permanência: {candidate_data.get('average_tenure', '')} anos\n"
            f"Resumo: {candidate_data.get('summary', '')}\n"
        )
    
    system_prompt = (
        "Você é um recrutador técnico. Analise os perfis dos candidatos abaixo com base nesta DESCRIÇÃO DA VAGA.\n\n"
        "IMPORTANTE: Todas as respostas devem ser em PORTUGUÊS (Brasil). Campos de texto, justificativas e valores devem estar em português.\n\n"
        f"DESCRIÇÃO DA VAGA:\n{job_description}\n\n"
        f"TÍTULOS DA VAGA (variações PT/EN): {titles}\n\n"
        "Calcule a aderência de 0 a 100% seguindo os pesos abaixo:\n"
        f"{weights_json}\n\n"
        "PERFIS DOS CANDIDATOS:\n"
        f"{candidates_text}\n\n"
        "Regras:\n"
        "- Retorne apenas JSON válido (sem markdown).\n"
        "- Retorne um ARRAY de objetos, um para cada candidato, na mesma ordem.\n"
        "- Justificativa técnica deve ser UMA FRASE CURTA (máximo 150 caracteres) resumindo os principais pontos de aderência.\n\n"
        "Retorne exatamente no formato (ARRAY):\n"
        "[\n"
        "  {\n"
        '    "adherence": 0,\n'
        '    "technical_justification": "string"\n'
        "  }\n"
        "]\n"
    )
    
    client = genai.Client(api_key=api_key)
    payload = [system_prompt]
    
    last_error = None
    model_candidates = ["models/gemini-2.0-flash"]
    backoff_seconds = [3, 8, 15, 30]
    for attempt in range(4):
        for model_name in model_candidates:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=payload,
                )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if not last_error:
            break
        error_str = str(last_error)
        if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
            wait_time = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            time.sleep(wait_time)
        elif "503" in error_str or "UNAVAILABLE" in error_str:
            time.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
        else:
            time.sleep(3)
    if last_error:
        raise last_error
    
    data = _extract_json(response.text)
    
    # Garante que é uma lista
    if not isinstance(data, list):
        data = [data]
    
    # Valida que temos o mesmo número de resultados que candidatos enviados
    if len(data) != len(candidates_data):
        raise RuntimeError(
            f"O LLM retornou {len(data)} resultado(s), mas foram enviados {len(candidates_data)} candidato(s). "
            "Tente novamente ou processe em lotes menores."
        )
    
    results = []
    for item in data:
        results.append({
            "adherence": item.get("adherence"),
            "technical_justification": item.get("technical_justification") or "",
        })
    
    return results


def extract_candidate_no_ranking(
    pdf_path: str | Path,
) -> dict:
    """Processa um único PDF sem rankeamento."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não definido no ambiente.")

    system_prompt = _build_system_prompt_no_ranking(is_batch=False)
    client = genai.Client(api_key=api_key)

    with open(pdf_path, "rb") as pdf_file:
        payload = [
            types.Part.from_bytes(data=pdf_file.read(), mime_type="application/pdf"),
            system_prompt,
        ]
        last_error = None
        model_candidates = [
            "models/gemini-2.0-flash",
        ]
        backoff_seconds = [3, 8, 15, 30]
        for attempt in range(4):
            for model_name in model_candidates:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=payload,
                    )
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
            if not last_error:
                break
            error_str = str(last_error)
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                wait_time = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                time.sleep(wait_time)
            elif "503" in error_str or "UNAVAILABLE" in error_str:
                time.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
            else:
                time.sleep(3)
        if last_error:
            raise last_error
    data = _extract_json(response.text)

    return {
        "name": data.get("name") or "",
        "linkedin_url": _normalize_linkedin_url(data.get("linkedin_url") or ""),
        "location": data.get("location") or "",
        "current_title": data.get("current_title") or "",
        "current_company": data.get("current_company") or "",
        "skills": _normalize_list(data.get("skills")),
        "technologies": _normalize_list(data.get("technologies")),
        "languages": _normalize_list(data.get("languages")),
        "certifications": _normalize_list(data.get("certifications")),
        "average_tenure_years": data.get("average_tenure_years"),
        "experience_time_years": data.get("experience_time_years"),
        "seniority": data.get("seniority") or "",
    }
