import re
from decimal import Decimal
from pathlib import Path
import unicodedata
import time

from pypdf import PdfReader

from .models import Candidate, CandidateJob
from .llm_extractor import (
    extract_candidate_with_llm,
    extract_candidates_batch_with_llm,
    extract_candidate_no_ranking,
    extract_candidates_batch_no_ranking,
    calculate_adherence_for_candidate,
    calculate_adherence_batch_for_candidates,
)


SECTION_TITLES = {
    "contact",
    "contato",
    "top skills",
    "principais competências",
    "technologies",
    "tecnologias",
    "languages",
    "idiomas",
    "certifications",
    "certificações",
    "certificacoes",
    "summary",
    "resumo",
    "experience",
    "experiência",
    "education",
    "formação acadêmica",
    "formacao academica",
}


def _fix_mojibake(text: str) -> str:
    def score(value: str) -> int:
        return value.count("�") + value.count("Ã") + value.count("Â")

    candidates = [text]
    try:
        candidates.append(text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore"))
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    try:
        candidates.append(text.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore"))
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    best = min(candidates, key=score)
    return best


def _clean_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("page ") or line.startswith("--") or line.endswith("--"):
            continue
        if line.lower().startswith("page") and "of" in line.lower():
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        lines.append(line)
    return lines


def _find_linkedin_url(text: str) -> str:
    match = re.search(r"(https?://)?(www\.)?linkedin\.com/in/[^\s)]+", text, re.I)
    if not match:
        return ""
    url = match.group(0)
    if not url.startswith("http"):
        url = f"https://{url}"
    return url


def _find_name(lines: list[str]) -> tuple[str, int]:
    def is_name_candidate(value: str) -> bool:
        lower = value.lower()
        if lower in SECTION_TITLES:
            return False
        if "linkedin.com" in lower or "http" in lower:
            return False
        if "linkedin" in lower and "(" in lower:
            return False
        if len(value) > 60 or len(value) < 3:
            return False
        if value.isupper():
            return False
        if re.search(r"\d", value):
            return False
        if re.search(r"\b(year|years|month|months|ano|anos|mes|meses)\b", lower):
            return False
        if re.search(r"\b(brazil|brasil)\b", lower):
            return False
        if "@" in value:
            return False
        return bool(re.search(r"[A-Za-zÀ-ÿ]", value))

    def is_section_like(value: str) -> bool:
        lower = value.lower()
        return lower in SECTION_TITLES or lower.startswith("page ")

    def looks_like_name(value: str) -> bool:
        parts = [p for p in value.split() if p]
        if len(parts) < 2 or len(parts) > 5:
            return False
        return all(part[0].isupper() for part in parts if part)

    role_keywords = (
        "engineer",
        "developer",
        "architect",
        "analyst",
        "manager",
        "consultant",
        "lead",
        "specialist",
        "engenheiro",
        "desenvolvedor",
        "arquiteto",
        "analista",
        "gerente",
        "consultor",
        "lider",
        "líder",
        "especialista",
    )

    # Prefer the first candidate before Summary/Resumo
    cutoff = None
    for i, line in enumerate(lines[:80]):
        if line.lower() in {"summary", "resumo"}:
            cutoff = i
            break
    search_range = lines[:cutoff] if cutoff is not None else lines[:60]

    best_score = -1
    best_line = ""
    best_idx = -1
    for i, line in enumerate(search_range):
        if is_section_like(line):
            continue
        if is_name_candidate(line):
            score = 0
            if looks_like_name(line):
                score += 2
            next_line = search_range[i + 1] if i + 1 < len(search_range) else ""
            next_lower = next_line.lower()
            if "|" in next_line or any(k in next_lower for k in role_keywords):
                score += 2
            if score > best_score:
                best_score = score
                best_line = line
                best_idx = i
            if score >= 4:
                return line, i

    if best_line:
        return best_line, best_idx

    # Fallback: first candidate in the first 60 lines
    for i, line in enumerate(lines[:60]):
        if is_name_candidate(line):
            return line, i

    return "", -1


def _find_location(lines: list[str], start_idx: int) -> str:
    for i in range(start_idx, min(start_idx + 10, len(lines))):
        if re.search(r"\b(Brasil|Brazil)\b", lines[i]):
            return lines[i]
    for i in range(min(120, len(lines))):
        if re.search(r"\b(Brasil|Brazil)\b", lines[i]):
            return lines[i]
    return ""


def _extract_headline(lines: list[str], name_idx: int, stop_idx: int) -> str:
    if name_idx < 0:
        return ""
    headline_lines = []
    for line in lines[name_idx + 1:stop_idx]:
        if line.lower() in SECTION_TITLES:
            break
        headline_lines.append(line)
    return " ".join(headline_lines).strip()


def _extract_skills(lines: list[str]) -> str:
    starts = {"top skills", "principais competências"}
    stops = SECTION_TITLES - starts
    start_idx = None
    for i, line in enumerate(lines[:80]):
        if line.lower() in starts:
            start_idx = i + 1
            break
    if start_idx is None:
        return ""

    skills = []
    for line in lines[start_idx:]:
        if line.lower() in stops:
            break
        if line:
            skills.append(line)
        if len(skills) >= 20:
            break
    return ", ".join(skills)


def _filter_skills(skills: str, name: str, location: str) -> str:
    if not skills:
        return skills
    name_norm = _normalize_text(name)
    location_norm = _normalize_text(location)
    cleaned = []
    for item in [s.strip() for s in skills.split(",")]:
        if not item:
            continue
        item_norm = _normalize_text(item)
        if name_norm and name_norm in item_norm:
            continue
        if location_norm and location_norm in item_norm:
            continue
        if "|" in item:
            continue
        if len(item) > 80:
            continue
        cleaned.append(item)
    return ", ".join(cleaned)


def _extract_languages(lines: list[str]) -> str:
    starts = {"languages", "idiomas"}
    stops = SECTION_TITLES - starts
    start_idx = None
    for i, line in enumerate(lines[:120]):
        if line.lower() in starts:
            start_idx = i + 1
            break
    if start_idx is None:
        return ""

    items = []
    for line in lines[start_idx:]:
        if line.lower() in stops:
            break
        if line and "(" in line and ")" in line:
            items.append(line)
        if len(items) >= 10:
            break
    return ", ".join(items)


def _extract_summary(lines: list[str]) -> str:
    starts = {"summary", "resumo"}
    stops = SECTION_TITLES - starts
    start_idx = None
    for i, line in enumerate(lines[:120]):
        if line.lower() in starts:
            start_idx = i + 1
            break
    if start_idx is None:
        return ""

    paragraphs = []
    for line in lines[start_idx:]:
        if line.lower() in stops:
            break
        paragraphs.append(line)
        if len(paragraphs) >= 12:
            break
    return " ".join(paragraphs).strip()


def _extract_certifications(lines: list[str]) -> str:
    starts = {"certifications", "certificações", "certificacoes"}
    stops = SECTION_TITLES - starts
    start_idx = None
    for i, line in enumerate(lines[:140]):
        if line.lower() in starts:
            start_idx = i + 1
            break
    if start_idx is None:
        return ""

    items = []
    for line in lines[start_idx:]:
        if line.lower() in stops:
            break
        if (
            line
            and len(line) <= 80
            and "|" not in line
            and not re.search(r"\b(Brasil|Brazil)\b", line)
            and "linkedin" not in line.lower()
        ):
            items.append(line)
        if len(items) >= 15:
            break
    return ", ".join(items)


def _normalize_technologies(technologies: list[str]) -> list[str]:
    aliases = {
        "ai": "AI",
        "ia": "AI",
        "ml": "Machine Learning",
        "machine learning": "Machine Learning",
        "deep learning": "Deep Learning",
        "data science": "Data Science",
        "data engineering": "Data Engineering",
        "data analytics": "Data Analytics",
        "nlp": "NLP",
        "llm": "LLM",
        "generative ai": "Generative AI",
        "genai": "Generative AI",
        "rag": "RAG",
        "vector db": "Vector Database",
        "vector database": "Vector Database",
        "vector search": "Vector Search",
        "prompt engineering": "Prompt Engineering",
        "computer vision": "Computer Vision",
        "cv": "Computer Vision",
        "pytorch": "PyTorch",
        "tensorflow": "TensorFlow",
        "scikit learn": "scikit-learn",
        "sklearn": "scikit-learn",
        "keras": "Keras",
        "xgboost": "XGBoost",
        "lightgbm": "LightGBM",
        "catboost": "CatBoost",
        "hugging face": "Hugging Face",
        "langchain": "LangChain",
        "llamaindex": "LlamaIndex",
        "openai": "OpenAI",
        "azure openai": "Azure OpenAI",
        "bedrock": "Amazon Bedrock",
        "vertex ai": "Vertex AI",
        "databricks": "Databricks",
        "mlflow": "MLflow",
        "kubeflow": "Kubeflow",
        "airflow": "Apache Airflow",
        "prefect": "Prefect",
        "dbt": "dbt",
        "snowflake": "Snowflake",
        "bigquery": "BigQuery",
        "redshift": "Redshift",
        "synapse": "Azure Synapse",
        "spark": "Apache Spark",
        "hadoop": "Hadoop",
        "kafka": "Kafka",
        "flink": "Apache Flink",
        "beam": "Apache Beam",
        "hive": "Hive",
        "trino": "Trino",
        "presto": "Presto",
        "lakehouse": "Lakehouse",
        "delta lake": "Delta Lake",
        "iceberg": "Apache Iceberg",
        "hudi": "Apache Hudi",
        "aws": "AWS",
        "amazon web services": "AWS",
        "azure": "Azure",
        "gcp": "GCP",
        "google cloud": "GCP",
        "oracle cloud": "OCI",
        "oci": "OCI",
        "digitalocean": "DigitalOcean",
        "docker": "Docker",
        "kubernetes": "Kubernetes",
        "k8s": "Kubernetes",
        "openshift": "OpenShift",
        "helm": "Helm",
        "argo cd": "ArgoCD",
        "argocd": "ArgoCD",
        "istio": "Istio",
        "linkerd": "Linkerd",
        "terraform": "Terraform",
        "pulumi": "Pulumi",
        "cloudformation": "CloudFormation",
        "ansible": "Ansible",
        "chef": "Chef",
        "puppet": "Puppet",
        "packer": "Packer",
        "redis": "Redis",
        "memcached": "Memcached",
        "elasticsearch": "Elasticsearch",
        "opensearch": "OpenSearch",
        "logstash": "Logstash",
        "kibana": "Kibana",
        "grafana": "Grafana",
        "prometheus": "Prometheus",
        "loki": "Loki",
        "datadog": "Datadog",
        "new relic": "New Relic",
        "splunk": "Splunk",
        "sentry": "Sentry",
        "opentelemetry": "OpenTelemetry",
        "postgresql": "PostgreSQL",
        "postgres": "PostgreSQL",
        "sql server": "SQL Server",
        "mysql": "MySQL",
        "mariadb": "MariaDB",
        "oracle": "Oracle",
        "sqlite": "SQLite",
        "cassandra": "Cassandra",
        "couchbase": "Couchbase",
        "couchdb": "CouchDB",
        "neo4j": "Neo4j",
        "arango": "ArangoDB",
        "mongodb": "MongoDB",
        "dynamodb": "DynamoDB",
        "kafka": "Kafka",
        "rabbitmq": "RabbitMQ",
        "activemq": "ActiveMQ",
        "sqs": "SQS",
        "sns": "SNS",
        "eventbridge": "EventBridge",
        "kinesis": "Kinesis",
        "java": "Java",
        "python": "Python",
        "go": "Go",
        "golang": "Go",
        "ruby": "Ruby",
        "php": "PHP",
        "c": "C",
        "c++": "C++",
        "rust": "Rust",
        "scala": "Scala",
        "kotlin": "Kotlin",
        "swift": "Swift",
        "objective-c": "Objective-C",
        "javascript": "JavaScript",
        "js": "JavaScript",
        "typescript": "TypeScript",
        "ts": "TypeScript",
        "angular": "Angular",
        "react": "React",
        "vue": "Vue.js",
        "svelte": "Svelte",
        "node.js": "Node.js",
        "nodejs": "Node.js",
        "spring boot": "Spring Boot",
        "spring": "Spring",
        "django": "Django",
        "flask": "Flask",
        "fastapi": "FastAPI",
        "express": "Express",
        "nest": "NestJS",
        "nestjs": "NestJS",
        "laravel": "Laravel",
        "rails": "Ruby on Rails",
        "ruby on rails": "Ruby on Rails",
        "dotnet": ".NET",
        "azure devops": "Azure DevOps",
        "jenkins": "Jenkins",
        "github actions": "GitHub Actions",
        "gitlab ci": "GitLab CI",
        "circleci": "CircleCI",
        "travis": "Travis CI",
        "bamboo": "Bamboo",
        "sonarqube": "SonarQube",
        "github": "GitHub",
        "gitlab": "GitLab",
        "bitbucket": "Bitbucket",
        "git": "Git",
        "jira": "Jira",
        "confluence": "Confluence",
        "trello": "Trello",
        "asana": "Asana",
        "monday": "Monday.com",
        ".net": ".NET",
        ".net core": ".NET Core",
        ".net framework": ".NET Framework",
        "c#": "C#",
        "graphql": "GraphQL",
        "rest": "REST",
        "grpc": "gRPC",
        "soap": "SOAP",
        "microservices": "Microservices",
        "event-driven": "Event-Driven",
        "eda": "Event-Driven",
        "ddd": "DDD",
        "cqrs": "CQRS",
        "tdd": "TDD",
        "ci/cd": "CI/CD",
        "oauth": "OAuth",
        "oauth2": "OAuth2",
        "oidc": "OpenID Connect",
        "jwt": "JWT",
        "saml": "SAML",
        "keycloak": "Keycloak",
        "okta": "Okta",
        "linux": "Linux",
        "windows": "Windows",
        "macos": "macOS",
    }

    normalized = []
    seen = set()
    for item in technologies:
        clean = item.strip().strip("-•")
        if not clean:
            continue
        key = _normalize_text(clean)
        if key in aliases:
            label = aliases[key]
        else:
            label = clean
        norm_key = _normalize_text(label)
        if norm_key not in seen:
            normalized.append(label)
            seen.add(norm_key)
    return normalized


def _extract_technologies(lines: list[str], text: str) -> str:
    starts = {"technologies", "tecnologias"}
    stops = SECTION_TITLES - starts
    start_idx = None
    for i, line in enumerate(lines[:120]):
        if line.lower() in starts:
            start_idx = i + 1
            break

    technologies = []
    if start_idx is not None:
        for line in lines[start_idx:]:
            if line.lower() in stops:
                break
            if line:
                technologies.append(line)
            if len(technologies) >= 30:
                break

    known_patterns = [
        (r"\bai\b", "AI"),
        (r"\bml\b", "Machine Learning"),
        (r"\bmachine learning\b", "Machine Learning"),
        (r"\bdeep learning\b", "Deep Learning"),
        (r"\bdata science\b", "Data Science"),
        (r"\bdata engineering\b", "Data Engineering"),
        (r"\bnlp\b", "NLP"),
        (r"\bllm\b", "LLM"),
        (r"\bgenerative ai\b", "Generative AI"),
        (r"\brag\b", "RAG"),
        (r"\bvector db\b", "Vector Database"),
        (r"\bvector database\b", "Vector Database"),
        (r"\bprompt engineering\b", "Prompt Engineering"),
        (r"\bcomputer vision\b", "Computer Vision"),
        (r"\bpytorch\b", "PyTorch"),
        (r"\btensorflow\b", "TensorFlow"),
        (r"\bscikit[- ]learn\b", "scikit-learn"),
        (r"\bkeras\b", "Keras"),
        (r"\bxgboost\b", "XGBoost"),
        (r"\blightgbm\b", "LightGBM"),
        (r"\bcatboost\b", "CatBoost"),
        (r"\bhugging face\b", "Hugging Face"),
        (r"\blangchain\b", "LangChain"),
        (r"\bllamaindex\b", "LlamaIndex"),
        (r"\bopenai\b", "OpenAI"),
        (r"\bazure openai\b", "Azure OpenAI"),
        (r"\bbedrock\b", "Amazon Bedrock"),
        (r"\bvertex ai\b", "Vertex AI"),
        (r"\bdatabricks\b", "Databricks"),
        (r"\bmlflow\b", "MLflow"),
        (r"\bkubeflow\b", "Kubeflow"),
        (r"\bapache airflow\b", "Apache Airflow"),
        (r"\bairflow\b", "Apache Airflow"),
        (r"\bprefect\b", "Prefect"),
        (r"\bdbt\b", "dbt"),
        (r"\bsnowflake\b", "Snowflake"),
        (r"\bbigquery\b", "BigQuery"),
        (r"\bredshift\b", "Redshift"),
        (r"\bazure synapse\b", "Azure Synapse"),
        (r"\bapache spark\b", "Apache Spark"),
        (r"\bspark\b", "Apache Spark"),
        (r"\bhadoop\b", "Hadoop"),
        (r"\bflink\b", "Apache Flink"),
        (r"\bapache beam\b", "Apache Beam"),
        (r"\bhive\b", "Hive"),
        (r"\btrino\b", "Trino"),
        (r"\bpresto\b", "Presto"),
        (r"\bdelta lake\b", "Delta Lake"),
        (r"\bapache iceberg\b", "Apache Iceberg"),
        (r"\bapache hudi\b", "Apache Hudi"),
        (r"\baws\b", "AWS"),
        (r"\bamazon web services\b", "AWS"),
        (r"\bazure\b", "Azure"),
        (r"\bgcp\b", "GCP"),
        (r"\bgoogle cloud\b", "GCP"),
        (r"\boracle cloud\b", "OCI"),
        (r"\boci\b", "OCI"),
        (r"\bdigitalocean\b", "DigitalOcean"),
        (r"\bdocker\b", "Docker"),
        (r"\bkubernetes\b", "Kubernetes"),
        (r"\bopenshift\b", "OpenShift"),
        (r"\bhelm\b", "Helm"),
        (r"\bistio\b", "Istio"),
        (r"\blinkerd\b", "Linkerd"),
        (r"\bterraform\b", "Terraform"),
        (r"\bpulumi\b", "Pulumi"),
        (r"\bcloudformation\b", "CloudFormation"),
        (r"\bansible\b", "Ansible"),
        (r"\bchef\b", "Chef"),
        (r"\bpuppet\b", "Puppet"),
        (r"\bpacker\b", "Packer"),
        (r"\bredis\b", "Redis"),
        (r"\bmemcached\b", "Memcached"),
        (r"\belasticsearch\b", "Elasticsearch"),
        (r"\bopensearch\b", "OpenSearch"),
        (r"\blogstash\b", "Logstash"),
        (r"\bkibana\b", "Kibana"),
        (r"\bgrafana\b", "Grafana"),
        (r"\bprometheus\b", "Prometheus"),
        (r"\bloki\b", "Loki"),
        (r"\bdatadog\b", "Datadog"),
        (r"\bnew relic\b", "New Relic"),
        (r"\bsplunk\b", "Splunk"),
        (r"\bsentry\b", "Sentry"),
        (r"\bopentelemetry\b", "OpenTelemetry"),
        (r"\bpostgresql\b", "PostgreSQL"),
        (r"\bsql server\b", "SQL Server"),
        (r"\bmysql\b", "MySQL"),
        (r"\bmariadb\b", "MariaDB"),
        (r"\boracle\b", "Oracle"),
        (r"\bsqlite\b", "SQLite"),
        (r"\bcassandra\b", "Cassandra"),
        (r"\bcouchbase\b", "Couchbase"),
        (r"\bcouchdb\b", "CouchDB"),
        (r"\bneo4j\b", "Neo4j"),
        (r"\barango\b", "ArangoDB"),
        (r"\bmongodb\b", "MongoDB"),
        (r"\bdynamodb\b", "DynamoDB"),
        (r"\bkafka\b", "Kafka"),
        (r"\brabbitmq\b", "RabbitMQ"),
        (r"\bactivemq\b", "ActiveMQ"),
        (r"\bsqs\b", "SQS"),
        (r"\bsns\b", "SNS"),
        (r"\beventbridge\b", "EventBridge"),
        (r"\bkinesis\b", "Kinesis"),
        (r"\bjava\b", "Java"),
        (r"\bpython\b", "Python"),
        (r"\bgolang\b", "Go"),
        (r"\bgo\b", "Go"),
        (r"\bruby\b", "Ruby"),
        (r"\bphp\b", "PHP"),
        (r"\brust\b", "Rust"),
        (r"\bscala\b", "Scala"),
        (r"\bkotlin\b", "Kotlin"),
        (r"\bjavascript\b", "JavaScript"),
        (r"\btypescript\b", "TypeScript"),
        (r"\bangular\b", "Angular"),
        (r"\breact\b", "React"),
        (r"\bvue\.js\b", "Vue.js"),
        (r"\bvue\b", "Vue.js"),
        (r"\bsvelte\b", "Svelte"),
        (r"\bnode\.js\b", "Node.js"),
        (r"\bnodejs\b", "Node.js"),
        (r"\bspring boot\b", "Spring Boot"),
        (r"\bspring\b", "Spring"),
        (r"\bdjango\b", "Django"),
        (r"\bflask\b", "Flask"),
        (r"\bfastapi\b", "FastAPI"),
        (r"\bexpress\b", "Express"),
        (r"\bnestjs\b", "NestJS"),
        (r"\blaravel\b", "Laravel"),
        (r"\bruby on rails\b", "Ruby on Rails"),
        (r"\bdotnet\b", ".NET"),
        (r"\bazure devops\b", "Azure DevOps"),
        (r"\bjenkins\b", "Jenkins"),
        (r"\bgithub actions\b", "GitHub Actions"),
        (r"\bgitlab ci\b", "GitLab CI"),
        (r"\bcircleci\b", "CircleCI"),
        (r"\btravis ci\b", "Travis CI"),
        (r"\bbamboo\b", "Bamboo"),
        (r"\bsonarqube\b", "SonarQube"),
        (r"\bgithub\b", "GitHub"),
        (r"\bgitlab\b", "GitLab"),
        (r"\bbitbucket\b", "Bitbucket"),
        (r"\bgit\b", "Git"),
        (r"\bjira\b", "Jira"),
        (r"\bconfluence\b", "Confluence"),
        (r"\btrello\b", "Trello"),
        (r"\basana\b", "Asana"),
        (r"\bmonday\b", "Monday.com"),
        (r"\b\.net\b", ".NET"),
        (r"\b\.net core\b", ".NET Core"),
        (r"\b\.net framework\b", ".NET Framework"),
        (r"\bc#\b", "C#"),
        (r"\bgraphql\b", "GraphQL"),
        (r"\brest\b", "REST"),
        (r"\bgrpc\b", "gRPC"),
        (r"\bsoap\b", "SOAP"),
        (r"\bmicroservices\b", "Microservices"),
        (r"\bevent[- ]driven\b", "Event-Driven"),
        (r"\beda\b", "Event-Driven"),
        (r"\bddd\b", "DDD"),
        (r"\bcqrs\b", "CQRS"),
        (r"\btdd\b", "TDD"),
        (r"\bci/cd\b", "CI/CD"),
        (r"\boauth2\b", "OAuth2"),
        (r"\boauth\b", "OAuth"),
        (r"\boidc\b", "OpenID Connect"),
        (r"\bjwt\b", "JWT"),
        (r"\bsaml\b", "SAML"),
        (r"\bkeycloak\b", "Keycloak"),
        (r"\bokta\b", "Okta"),
        (r"\blinux\b", "Linux"),
        (r"\bwindows\b", "Windows"),
        (r"\bmacos\b", "macOS"),
    ]

    normalized_section = _normalize_technologies(technologies)
    seen = set(_normalize_text(item) for item in normalized_section)
    text_norm = _normalize_text(text)
    for pattern, label in known_patterns:
        if re.search(pattern, text_norm, re.I):
            key = _normalize_text(label)
            if key not in seen:
                normalized_section.append(label)
                seen.add(key)

    normalized_section = _normalize_technologies(normalized_section)
    return ", ".join(normalized_section)


def _extract_experience(lines: list[str]) -> tuple[str, str]:
    blocks = _extract_experience_blocks(lines)
    if not blocks:
        return "", ""
    first = blocks[0]
    return first.get("company", ""), first.get("title", "")


def _extract_experience_years(text: str) -> Decimal | None:
    match = re.search(r"(\d{1,2})\+?\s+years", text, re.I)
    if not match:
        match = re.search(r"(\d{1,2})\+?\s+anos", text, re.I)
    if not match:
        return None
    return Decimal(match.group(1))


def _duration_to_months(text: str) -> int | None:
    normalized = text.lower()
    year_match = re.search(r"(\d+)\s*(year|years|ano|anos)", normalized)
    month_match = re.search(r"(\d+)\s*(month|months|mes|meses)", normalized)
    if not year_match and not month_match:
        return None
    years = int(year_match.group(1)) if year_match else 0
    months = int(month_match.group(1)) if month_match else 0
    return years * 12 + months


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip().lower()


def _extract_experience_blocks(lines: list[str]) -> list[dict]:
    exp_idx = None
    for i, line in enumerate(lines):
        if line.lower() in {"experience", "experiência"}:
            exp_idx = i + 1
            break
    if exp_idx is None:
        return []

    end_idx = len(lines)
    for i in range(exp_idx, len(lines)):
        if lines[i].lower() in {"education", "formação acadêmica", "formacao academica"}:
            end_idx = i
            break

    blocks = []
    window = []
    current_company = ""
    sliced = lines[exp_idx:end_idx]
    for i, line in enumerate(sliced):
        if line:
            window.append(line)
            if len(window) > 4:
                window = window[-4:]

        next_line = sliced[i + 1] if i + 1 < len(sliced) else ""
        if (
            next_line
            and "(" not in next_line
            and ")" not in next_line
            and "-" not in next_line
            and _duration_to_months(next_line) is not None
        ):
            current_company = line
            continue

        if "(" not in line or ")" not in line:
            continue

        match = re.search(r"\(([^)]+)\)", line)
        if not match:
            continue
        months = _duration_to_months(match.group(1))
        if len(window) >= 2:
            title = window[-2]
            company = current_company or (window[-3] if len(window) >= 3 else "")
            location = ""
            if i + 1 < len(sliced):
                location = sliced[i + 1]
            blocks.append(
                {
                    "company": company,
                    "title": title,
                    "location": location,
                    "months": months or 0,
                }
            )
    return blocks


def _extract_average_tenure(blocks: list[dict]) -> Decimal | None:
    durations = [b.get("months", 0) for b in blocks if b.get("months", 0) > 0]
    if not durations:
        return None
    average_months = sum(durations) / len(durations)
    average_years = round(average_months / 12, 1)
    return Decimal(str(average_years))


def _extract_total_experience_years(blocks: list[dict]) -> Decimal | None:
    durations = [b.get("months", 0) for b in blocks if b.get("months", 0) > 0]
    if not durations:
        return None
    total_months = sum(durations)
    total_years = round(total_months / 12, 1)
    return Decimal(str(total_years))


def _extract_role_experience_years(blocks: list[dict], role_titles: list[str]) -> Decimal | None:
    if not role_titles:
        return None
    normalized_roles = [_normalize_text(role) for role in role_titles if role.strip()]
    if not normalized_roles:
        return None
    total_months = 0
    for block in blocks:
        title = _normalize_text(block.get("title", ""))
        if not title:
            continue
        if any(role in title for role in normalized_roles):
            total_months += block.get("months", 0)
    if total_months <= 0:
        return None
    total_years = round(total_months / 12, 1)
    return Decimal(str(total_years))


def _infer_seniority_from_years(total_years: Decimal | None) -> str:
    if total_years is None:
        return ""
    years = float(total_years)
    if years < 1:
        return "Trainee"
    if years < 2:
        return "Junior"
    if years < 5:
        return "Pleno"
    if years < 8:
        return "Senior"
    return "Especialista"
    return ""


def parse_candidate_from_pdf(path: str | Path, role_titles: list[str] | None = None) -> dict:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = _fix_mojibake(text)
    lines = _clean_lines(text)

    name, name_idx = _find_name(lines)
    location = _find_location(lines, name_idx + 1 if name_idx >= 0 else 0)
    stop_idx = lines.index(location) if location in lines else min(name_idx + 6, len(lines))
    headline = _extract_headline(lines, name_idx, stop_idx)
    summary = _extract_summary(lines)
    skills = _extract_skills(lines)
    technologies = _extract_technologies(lines, text)
    languages = _extract_languages(lines)
    certifications_raw = _extract_certifications(lines)
    linkedin_url = _find_linkedin_url(text)
    experience_blocks = _extract_experience_blocks(lines)
    if experience_blocks:
        current_company = experience_blocks[0].get("company", "")
        current_title = experience_blocks[0].get("title", "")
    else:
        current_company, current_title = "", ""

    if not current_title:
        current_title = headline

    role_years = _extract_role_experience_years(experience_blocks, role_titles or [])
    if role_titles:
        experience_time = role_years
    else:
        experience_time = _extract_total_experience_years(experience_blocks)
    seniority = _infer_seniority_from_years(experience_time)
    average_tenure = _extract_average_tenure(experience_blocks)

    certifications = certifications_raw
    if certifications:
        items = [item.strip() for item in certifications.split(",") if item.strip()]
        filtered = []
        name_norm = _normalize_text(name)
        headline_norm = _normalize_text(headline)
        location_norm = _normalize_text(location)
        for item in items:
            item_norm = _normalize_text(item)
            if not item_norm:
                continue
            if name_norm and name_norm in item_norm:
                continue
            if headline_norm and headline_norm in item_norm:
                continue
            if location_norm and location_norm in item_norm:
                continue
            filtered.append(item)
        certifications = ", ".join(filtered)

    skills = _filter_skills(skills, name, location)

    return {
        "name": name,
        "current_title": current_title or headline,
        "current_company": current_company,
        "location": location,
        "linkedin_url": linkedin_url,
        "summary": summary,
        "skills": skills,
        "technologies": technologies,
        "languages": languages,
        "certifications": certifications,
        "seniority": seniority,
        "experience_time": experience_time,
        "average_tenure": average_tenure,
    }


def import_candidates_from_folder(
    folder_path: str,
    job_description: str,
    weights: dict[str, int],
    role_title: str | None = None,
    job_id: int | None = None,
    user_id=None,
    shared_pool: bool = False,
    progress_callback=None,
) -> dict:
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Pasta nao encontrada: {folder}")

    pdf_files = [folder] if folder.is_file() else sorted(folder.glob("*.pdf"))
    total_files = len(pdf_files)
    if progress_callback:
        progress_callback(total=total_files, processed=0, current=None, status="running")
    role_titles = []
    if role_title:
        role_titles = [item.strip() for item in role_title.split("/") if item.strip()]
    created = 0
    updated = 0
    skipped = 0
    errors = 0
    error_details = []
    
    # Processa em lotes de 10 PDFs
    batch_size = 10
    processed_count = 0
    
    for batch_start in range(0, len(pdf_files), batch_size):
        batch = pdf_files[batch_start:batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(pdf_files) + batch_size - 1) // batch_size
        
        try:
            # Processa o lote inteiro
            results = extract_candidates_batch_with_llm(
                batch,
                job_description=job_description,
                weights=weights,
                role_titles=role_titles,
            )
            
            # Processa cada resultado do lote
            for idx, data in enumerate(results):
                pdf_file = batch[idx]
                
                linkedin_url = data.get("linkedin_url", "")
                if not data.get("name") or not linkedin_url:
                    skipped += 1
                    processed_count += 1  # Conta como processado mesmo que pulado
                    if progress_callback:
                        progress_callback(
                            total=total_files,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {pdf_file.name} (pulado)",
                            status="running",
                            errors=errors,
                        )
                    continue

                try:
                    candidate_payload = {
                        "name": data.get("name") or "",
                        "current_title": data.get("current_title") or "",
                        "current_company": data.get("current_company") or "",
                        "location": data.get("location") or "",
                        "linkedin_url": linkedin_url,
                        "summary": "",
                        "skills": ", ".join(data.get("skills", [])),
                        "technologies": ", ".join(data.get("technologies", [])),
                        "languages": ", ".join(data.get("languages", [])),
                        "certifications": ", ".join(data.get("certifications", [])),
                        "experience_time": data.get("experience_time_years"),
                        "average_tenure": data.get("average_tenure_years"),
                        "seniority": data.get("seniority") or "",
                    }

                    if shared_pool:
                        qs = Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
                    else:
                        qs = Candidate.objects.filter(user_id=user_id, linkedin_url__iexact=linkedin_url) if user_id else Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
                    candidate = qs.first()
                    if candidate:
                        changed = False
                        for field, value in candidate_payload.items():
                            # Normaliza None para string vazia em campos de texto
                            if field in ("name", "current_title", "current_company", "location", "linkedin_url", "summary", "skills", "technologies", "languages", "certifications", "seniority"):
                                if value is None:
                                    value = ""
                            # Ignora apenas se for None e o campo não aceitar None
                            if value is None and field not in ("experience_time", "average_tenure"):
                                continue
                            if getattr(candidate, field) != value:
                                setattr(candidate, field, value)
                                changed = True
                        if changed:
                            candidate.save()
                            updated += 1
                    else:
                        # Garante que todos os campos de texto sejam strings, nunca None
                        safe_payload = {}
                        for field, value in candidate_payload.items():
                            if field in ("name", "current_title", "current_company", "location", "linkedin_url", "summary", "skills", "technologies", "languages", "certifications", "seniority"):
                                safe_payload[field] = value if value is not None else ""
                            else:
                                safe_payload[field] = value
                        if user_id:
                            safe_payload["user_id"] = user_id
                        candidate = Candidate.objects.create(**safe_payload)
                        created += 1

                    if job_id:
                        CandidateJob.objects.update_or_create(
                            job_id=job_id,
                            candidate=candidate,
                            defaults={
                                "adherence_score": data.get("adherence"),
                                "technical_justification": data.get("technical_justification", ""),
                            },
                        )
                    
                    # Incrementa contador apenas após salvar com sucesso
                    processed_count += 1
                    
                except Exception as save_exc:
                    errors += 1
                    error_msg = str(save_exc)
                    if "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
                        error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                    else:
                        error_details.append(f"{pdf_file.name}: Erro ao salvar - {error_msg[:100]}")
                    processed_count += 1  # Conta como processado mesmo com erro
                
                if progress_callback:
                    progress_callback(
                        total=total_files,
                        processed=processed_count,
                        current=f"Lote {batch_num}/{total_batches}: {pdf_file.name}",
                        status="running",
                        errors=errors,
                    )
            
            # Aguarda entre lotes (menos tempo já que processa 10 de uma vez)
            if batch_start + batch_size < len(pdf_files):
                time.sleep(1)
                
        except Exception as exc:
            # Se o lote falhar, tenta processar individualmente
            error_msg = str(exc)
            for pdf_file in batch:
                try:
                    data = extract_candidate_with_llm(
                        pdf_file,
                        job_description=job_description,
                        weights=weights,
                        role_titles=role_titles,
                    )
                    linkedin_url = data.get("linkedin_url", "")
                    if not data.get("name") or not linkedin_url:
                        skipped += 1
                        processed_count += 1  # Conta como processado mesmo que pulado
                        if progress_callback:
                            progress_callback(
                                total=total_files,
                                processed=processed_count,
                                current=f"Lote {batch_num}/{total_batches}: {pdf_file.name} (pulado)",
                                status="running",
                                errors=errors,
                            )
                        continue

                    try:
                        candidate_payload = {
                            "name": data.get("name") or "",
                            "current_title": data.get("current_title") or "",
                            "current_company": data.get("current_company") or "",
                            "location": data.get("location") or "",
                            "linkedin_url": linkedin_url,
                            "summary": "",
                            "skills": ", ".join(data.get("skills", [])),
                            "technologies": ", ".join(data.get("technologies", [])),
                            "languages": ", ".join(data.get("languages", [])),
                            "certifications": ", ".join(data.get("certifications", [])),
                            "experience_time": data.get("experience_time_years"),
                            "average_tenure": data.get("average_tenure_years"),
                            "seniority": data.get("seniority") or "",
                        }

                        if shared_pool:
                            qs = Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
                        else:
                            qs = Candidate.objects.filter(user_id=user_id, linkedin_url__iexact=linkedin_url) if user_id else Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
                        candidate = qs.first()
                        if candidate:
                            changed = False
                            for field, value in candidate_payload.items():
                                # Normaliza None para string vazia em campos de texto
                                if field in ("name", "current_title", "current_company", "location", "linkedin_url", "summary", "skills", "technologies", "languages", "certifications", "seniority"):
                                    if value is None:
                                        value = ""
                                # Ignora apenas se for None e o campo não aceitar None
                                if value is None and field not in ("experience_time", "average_tenure"):
                                    continue
                                if getattr(candidate, field) != value:
                                    setattr(candidate, field, value)
                                    changed = True
                            if changed:
                                candidate.save()
                                updated += 1
                        else:
                            # Garante que todos os campos de texto sejam strings, nunca None
                            safe_payload = {}
                            for field, value in candidate_payload.items():
                                if field in ("name", "current_title", "current_company", "location", "linkedin_url", "summary", "skills", "technologies", "languages", "certifications", "seniority"):
                                    safe_payload[field] = value if value is not None else ""
                                else:
                                    safe_payload[field] = value
                            if user_id:
                                safe_payload["user_id"] = user_id
                            candidate = Candidate.objects.create(**safe_payload)
                            created += 1

                        if job_id:
                            CandidateJob.objects.update_or_create(
                                job_id=job_id,
                                candidate=candidate,
                                defaults={
                                    "adherence_score": data.get("adherence"),
                                    "technical_justification": data.get("technical_justification", ""),
                                },
                            )
                        
                        # Incrementa contador apenas após salvar com sucesso
                        processed_count += 1
                        
                    except Exception as save_exc:
                        errors += 1
                        save_error_msg = str(save_exc)
                        if "RESOURCE_EXHAUSTED" in save_error_msg or "429" in save_error_msg:
                            error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                        else:
                            error_details.append(f"{pdf_file.name}: Erro ao salvar - {save_error_msg[:100]}")
                        processed_count += 1  # Conta como processado mesmo com erro
                        
                except Exception as individual_exc:
                    errors += 1
                    individual_error_msg = str(individual_exc)
                    if "RESOURCE_EXHAUSTED" in individual_error_msg or "429" in individual_error_msg:
                        error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                    else:
                        error_details.append(f"{pdf_file.name}: {individual_error_msg[:100]}")
                    processed_count += 1  # Conta como processado mesmo com erro
                
                if progress_callback:
                    progress_callback(
                        total=total_files,
                        processed=processed_count,
                        current=f"Lote {batch_num}/{total_batches}: {pdf_file.name}",
                        status="running",
                        errors=errors,
                    )
                
                time.sleep(2)

    result = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "total": total_files,
        "error_details": error_details[:10],
    }
    if progress_callback:
        progress_callback(total=total_files, processed=total_files, current=None, status="completed")
    return result


def import_candidates_from_folder_no_ranking(
    folder_path: str,
    user_id=None,
    shared_pool: bool = False,
    progress_callback=None,
) -> dict:
    """Importa candidatos sem rankeamento (para banco de talentos). Candidatos ficam vinculados ao user_id."""
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Pasta não encontrada: {folder}")

    pdf_files = [folder] if folder.is_file() else sorted(folder.glob("*.pdf"))
    total_files = len(pdf_files)
    if progress_callback:
        progress_callback(total=total_files, processed=0, current=None, status="running")
    
    created = 0
    updated = 0
    skipped = 0
    errors = 0
    error_details = []
    
    # Processa em lotes de 10 PDFs
    batch_size = 10
    processed_count = 0
    
    for batch_start in range(0, len(pdf_files), batch_size):
        batch = pdf_files[batch_start:batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(pdf_files) + batch_size - 1) // batch_size
        
        try:
            # Processa o lote inteiro sem rankeamento
            results = extract_candidates_batch_no_ranking(batch)
            
            # Processa cada resultado do lote
            for idx, data in enumerate(results):
                pdf_file = batch[idx]
                
                linkedin_url = data.get("linkedin_url", "")
                if not data.get("name") or not linkedin_url:
                    skipped += 1
                    processed_count += 1
                    if progress_callback:
                        progress_callback(
                            total=total_files,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {pdf_file.name} (pulado)",
                            status="running",
                            errors=errors,
                        )
                    continue

                try:
                    candidate_payload = {
                        "name": data.get("name") or "",
                        "current_title": data.get("current_title") or "",
                        "current_company": data.get("current_company") or "",
                        "location": data.get("location") or "",
                        "linkedin_url": linkedin_url,
                        "summary": "",
                        "skills": ", ".join(data.get("skills", [])),
                        "technologies": ", ".join(data.get("technologies", [])),
                        "languages": ", ".join(data.get("languages", [])),
                        "certifications": ", ".join(data.get("certifications", [])),
                        "experience_time": data.get("experience_time_years"),
                        "average_tenure": data.get("average_tenure_years"),
                        "seniority": data.get("seniority") or "",
                    }

                    if shared_pool:
                        qs = Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
                    else:
                        qs = Candidate.objects.filter(user_id=user_id, linkedin_url__iexact=linkedin_url) if user_id else Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
                    candidate = qs.first()
                    if candidate:
                        changed = False
                        for field, value in candidate_payload.items():
                            # Normaliza None para string vazia em campos de texto
                            if field in ("name", "current_title", "current_company", "location", "linkedin_url", "summary", "skills", "technologies", "languages", "certifications", "seniority"):
                                if value is None:
                                    value = ""
                            # Ignora apenas se for None e o campo não aceitar None
                            if value is None and field not in ("experience_time", "average_tenure"):
                                continue
                            if getattr(candidate, field) != value:
                                setattr(candidate, field, value)
                                changed = True
                        if changed:
                            candidate.save()
                            updated += 1
                    else:
                        # Garante que todos os campos de texto sejam strings, nunca None
                        safe_payload = {}
                        for field, value in candidate_payload.items():
                            if field in ("name", "current_title", "current_company", "location", "linkedin_url", "summary", "skills", "technologies", "languages", "certifications", "seniority"):
                                safe_payload[field] = value if value is not None else ""
                            else:
                                safe_payload[field] = value
                        if user_id:
                            safe_payload["user_id"] = user_id
                        candidate = Candidate.objects.create(**safe_payload)
                        created += 1
                    
                    # Incrementa contador apenas após salvar com sucesso
                    processed_count += 1
                    
                except Exception as save_exc:
                    errors += 1
                    error_msg = str(save_exc)
                    if "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
                        error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                    else:
                        error_details.append(f"{pdf_file.name}: Erro ao salvar - {error_msg[:100]}")
                    processed_count += 1
                
                if progress_callback:
                    progress_callback(
                        total=total_files,
                        processed=processed_count,
                        current=f"Lote {batch_num}/{total_batches}: {pdf_file.name}",
                        status="running",
                        errors=errors,
                    )
            
            # Aguarda entre lotes
            if batch_start + batch_size < len(pdf_files):
                time.sleep(1)
                
        except Exception as exc:
            # Se o lote falhar, tenta processar individualmente
            error_msg = str(exc)
            for pdf_file in batch:
                try:
                    data = extract_candidate_no_ranking(pdf_file)
                    linkedin_url = data.get("linkedin_url", "")
                    if not data.get("name") or not linkedin_url:
                        skipped += 1
                        processed_count += 1
                        if progress_callback:
                            progress_callback(
                                total=total_files,
                                processed=processed_count,
                                current=f"Lote {batch_num}/{total_batches}: {pdf_file.name} (pulado)",
                                status="running",
                                errors=errors,
                            )
                        continue

                    try:
                        candidate_payload = {
                            "name": data.get("name") or "",
                            "current_title": data.get("current_title") or "",
                            "current_company": data.get("current_company") or "",
                            "location": data.get("location") or "",
                            "linkedin_url": linkedin_url,
                            "summary": "",
                            "skills": ", ".join(data.get("skills", [])),
                            "technologies": ", ".join(data.get("technologies", [])),
                            "languages": ", ".join(data.get("languages", [])),
                            "certifications": ", ".join(data.get("certifications", [])),
                            "experience_time": data.get("experience_time_years"),
                            "average_tenure": data.get("average_tenure_years"),
                            "seniority": data.get("seniority") or "",
                        }

                        qs = Candidate.objects.filter(user_id=user_id, linkedin_url__iexact=linkedin_url) if user_id else Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
                        candidate = qs.first()
                        if candidate:
                            changed = False
                            for field, value in candidate_payload.items():
                                # Normaliza None para string vazia em campos de texto
                                if field in ("name", "current_title", "current_company", "location", "linkedin_url", "summary", "skills", "technologies", "languages", "certifications", "seniority"):
                                    if value is None:
                                        value = ""
                                # Ignora apenas se for None e o campo não aceitar None
                                if value is None and field not in ("experience_time", "average_tenure"):
                                    continue
                                if getattr(candidate, field) != value:
                                    setattr(candidate, field, value)
                                    changed = True
                            if changed:
                                candidate.save()
                                updated += 1
                        else:
                            # Garante que todos os campos de texto sejam strings, nunca None
                            safe_payload = {}
                            for field, value in candidate_payload.items():
                                if field in ("name", "current_title", "current_company", "location", "linkedin_url", "summary", "skills", "technologies", "languages", "certifications", "seniority"):
                                    safe_payload[field] = value if value is not None else ""
                                else:
                                    safe_payload[field] = value
                            if user_id:
                                safe_payload["user_id"] = user_id
                            candidate = Candidate.objects.create(**safe_payload)
                            created += 1
                        
                        # Incrementa contador apenas após salvar com sucesso
                        processed_count += 1
                        
                    except Exception as save_exc:
                        errors += 1
                        save_error_msg = str(save_exc)
                        if "RESOURCE_EXHAUSTED" in save_error_msg or "429" in save_error_msg:
                            error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                        else:
                            error_details.append(f"{pdf_file.name}: Erro ao salvar - {save_error_msg[:100]}")
                        processed_count += 1
                        
                except Exception as individual_exc:
                    errors += 1
                    individual_error_msg = str(individual_exc)
                    if "RESOURCE_EXHAUSTED" in individual_error_msg or "429" in individual_error_msg:
                        error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                    else:
                        error_details.append(f"{pdf_file.name}: {individual_error_msg[:100]}")
                    processed_count += 1
                
                if progress_callback:
                    progress_callback(
                        total=total_files,
                        processed=processed_count,
                        current=f"Lote {batch_num}/{total_batches}: {pdf_file.name}",
                        status="running",
                        errors=errors,
                    )
                
                time.sleep(2)

    result = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "total": total_files,
        "error_details": error_details[:10],
    }
    if progress_callback:
        progress_callback(total=total_files, processed=processed_count, current=None, status="completed", result=result)
    return result


def search_and_rank_candidates_from_pool(
    job_id: int,
    job_description: str,
    weights: dict[str, int],
    role_title: str | None = None,
    progress_callback=None,
    filters: dict | None = None,
    user_id=None,
    shared_pool: bool = False,
) -> dict:
    """Busca candidatos no banco de talentos do usuário e calcula aderência para a vaga."""
    from .models import Candidate, CandidateJob
    
    # Busca candidatos do usuário não vinculados à vaga
    linked_candidate_ids = CandidateJob.objects.filter(job_id=job_id).values_list('candidate_id', flat=True)
    candidates = Candidate.objects.exclude(id__in=linked_candidate_ids)
    if user_id is not None and not shared_pool:
        candidates = candidates.filter(user_id=user_id)
    
    # Aplica filtros se fornecidos
    if filters:
        name_filter = filters.get('name', '').strip()
        location_filter = filters.get('location', '').strip()
        seniority_filter = filters.get('seniority', '').strip()
        company_filter = filters.get('company', '').strip()
        technologies_filter = filters.get('technologies', '').strip()
        skills_filter = filters.get('skills', '').strip()
        languages_filter = filters.get('languages', '').strip()
        certifications_filter = filters.get('certifications', '').strip()
        ready_only = filters.get('ready_only', False)
        
        if name_filter:
            candidates = candidates.filter(name__icontains=name_filter)
        if location_filter:
            candidates = candidates.filter(location__icontains=location_filter)
        if seniority_filter:
            candidates = candidates.filter(seniority__icontains=seniority_filter)
        if company_filter:
            candidates = candidates.filter(current_company__icontains=company_filter)
        if technologies_filter:
            candidates = candidates.filter(technologies__icontains=technologies_filter)
        if skills_filter:
            candidates = candidates.filter(skills__icontains=skills_filter)
        if languages_filter:
            candidates = candidates.filter(languages__icontains=languages_filter)
        if certifications_filter:
            candidates = candidates.filter(certifications__icontains=certifications_filter)
        if ready_only:
            candidates = candidates.exclude(ready_at__isnull=True)
    
    total_candidates = candidates.count()
    if progress_callback:
        progress_callback(total=total_candidates, processed=0, current=None, status="running")
    
    if total_candidates == 0:
        result = {
            "linked": 0,
            "errors": 0,
            "total": 0,
            "error_details": [],
        }
        if progress_callback:
            progress_callback(total=0, processed=0, current=None, status="completed", result=result)
        return result
    
    role_titles = []
    if role_title:
        role_titles = [item.strip() for item in role_title.split("/") if item.strip()]
    
    linked = 0
    errors = 0
    error_details = []
    
    # Processa em lotes de 10 candidatos
    batch_size = 10
    processed_count = 0
    
    candidates_list = list(candidates)
    
    for batch_start in range(0, len(candidates_list), batch_size):
        batch = candidates_list[batch_start:batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(candidates_list) + batch_size - 1) // batch_size
        
        try:
            # Prepara dados dos candidatos para o LLM
            candidates_data = []
            for candidate in batch:
                candidates_data.append({
                    "name": candidate.name or "",
                    "current_title": candidate.current_title or "",
                    "current_company": candidate.current_company or "",
                    "location": candidate.location or "",
                    "skills": candidate.skills or "",
                    "technologies": candidate.technologies or "",
                    "languages": candidate.languages or "",
                    "certifications": candidate.certifications or "",
                    "seniority": candidate.seniority or "",
                    "experience_time": str(candidate.experience_time) if candidate.experience_time else "",
                    "average_tenure": str(candidate.average_tenure) if candidate.average_tenure else "",
                    "summary": candidate.summary or "",
                })
            
            # Calcula aderência em lote
            results = calculate_adherence_batch_for_candidates(
                candidates_data,
                job_description=job_description,
                weights=weights,
                role_titles=role_titles,
            )
            
            # Cria CandidateJob para cada candidato
            for idx, (candidate, adherence_data) in enumerate(zip(batch, results)):
                try:
                    CandidateJob.objects.update_or_create(
                        job_id=job_id,
                        candidate=candidate,
                        defaults={
                            "adherence_score": adherence_data.get("adherence"),
                            "technical_justification": adherence_data.get("technical_justification", ""),
                        },
                    )
                    linked += 1
                    processed_count += 1
                    
                    if progress_callback:
                        progress_callback(
                            total=total_candidates,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {candidate.name}",
                            status="running",
                            errors=errors,
                        )
                except Exception as save_exc:
                    errors += 1
                    error_msg = str(save_exc)
                    error_details.append(f"{candidate.name}: Erro ao vincular - {error_msg[:100]}")
                    processed_count += 1
                    
                    if progress_callback:
                        progress_callback(
                            total=total_candidates,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {candidate.name} (erro)",
                            status="running",
                            errors=errors,
                        )
            
            # Aguarda entre lotes
            if batch_start + batch_size < len(candidates_list):
                time.sleep(1)
                
        except Exception as exc:
            # Se o lote falhar, tenta processar individualmente
            error_msg = str(exc)
            for candidate in batch:
                try:
                    candidate_data = {
                        "name": candidate.name or "",
                        "current_title": candidate.current_title or "",
                        "current_company": candidate.current_company or "",
                        "location": candidate.location or "",
                        "skills": candidate.skills or "",
                        "technologies": candidate.technologies or "",
                        "languages": candidate.languages or "",
                        "certifications": candidate.certifications or "",
                        "seniority": candidate.seniority or "",
                        "experience_time": str(candidate.experience_time) if candidate.experience_time else "",
                        "average_tenure": str(candidate.average_tenure) if candidate.average_tenure else "",
                        "summary": candidate.summary or "",
                    }
                    
                    adherence_data = calculate_adherence_for_candidate(
                        candidate_data,
                        job_description=job_description,
                        weights=weights,
                        role_titles=role_titles,
                    )
                    
                    CandidateJob.objects.update_or_create(
                        job_id=job_id,
                        candidate=candidate,
                        defaults={
                            "adherence_score": adherence_data.get("adherence"),
                            "technical_justification": adherence_data.get("technical_justification", ""),
                        },
                    )
                    linked += 1
                    processed_count += 1
                    
                    if progress_callback:
                        progress_callback(
                            total=total_candidates,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {candidate.name}",
                            status="running",
                            errors=errors,
                        )
                except Exception as individual_exc:
                    errors += 1
                    individual_error_msg = str(individual_exc)
                    error_details.append(f"{candidate.name}: {individual_error_msg[:100]}")
                    processed_count += 1
                    
                    if progress_callback:
                        progress_callback(
                            total=total_candidates,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {candidate.name} (erro)",
                            status="running",
                            errors=errors,
                        )
                
                time.sleep(2)

    result = {
        "linked": linked,
        "errors": errors,
        "total": total_candidates,
        "error_details": error_details[:10],
    }
    if progress_callback:
        progress_callback(total=total_candidates, processed=processed_count, current=None, status="completed", result=result)
    return result
