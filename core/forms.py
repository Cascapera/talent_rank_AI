import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Job, Candidate

User = get_user_model()


def _clean_cpf(value: str) -> str:
    """Remove tudo que não seja dígito e valida tamanho 11."""
    digits = re.sub(r"\D", "", value or "")
    if digits and len(digits) != 11:
        raise forms.ValidationError("CPF deve ter 11 dígitos.")
    return digits


class SignupForm(UserCreationForm):
    """Formulário de cadastro: User + telefone/CPF para pagamento futuro."""
    email = forms.EmailField(
        required=True,
        label="E-mail",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "seu@email.com"}),
    )
    first_name = forms.CharField(
        max_length=150,
        required=True,
        label="Nome",
        widget=forms.TextInput(attrs={"placeholder": "Seu nome"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        label="Sobrenome",
        widget=forms.TextInput(attrs={"placeholder": "Seu sobrenome"}),
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        label="Telefone",
        widget=forms.TextInput(attrs={"placeholder": "(11) 99999-9999"}),
    )
    cpf = forms.CharField(
        max_length=14,
        required=False,
        label="CPF",
        widget=forms.TextInput(attrs={"placeholder": "000.000.000-00"}),
    )

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "password1", "password2")
        labels = {"username": "Usuário"}
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "Nome de Usuário", "autocomplete": "username"}),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email and User.objects.filter(email=email).exists():
            raise forms.ValidationError("Este e-mail já está em uso.")
        return email

    def clean_cpf(self):
        return _clean_cpf(self.cleaned_data.get("cpf", ""))

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            from .models import Profile

            Profile.objects.update_or_create(
                user=user,
                defaults={
                    "phone": (self.cleaned_data.get("phone") or "").strip(),
                    "cpf": self.cleaned_data.get("cpf") or "",
                },
            )
        return user


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = (
            'title',
            'summary',
            'department',
            'seniority',
            'location',
            'stack',
            'contract_type',
            'salary_min',
            'salary_max',
            'language',
            'priority',
            'must_have',
            'nice_to_have',
            'undesirable',
            'boolean_search',
            'notes',
            'status',
        )
        labels = {
            'title': 'Título',
            'summary': 'Descrição resumida',
            'department': 'Área',
            'seniority': 'Senioridade',
            'location': 'Localização',
            'stack': 'Stack principal',
            'contract_type': 'Tipo de contratação',
            'salary_min': 'Salário mínimo',
            'salary_max': 'Salário máximo',
            'language': 'Idioma',
            'priority': 'Prioridade',
            'must_have': 'Skills obrigatórias',
            'nice_to_have': 'Skills desejáveis',
            'undesirable': 'Não desejáveis',
            'boolean_search': 'Busca booleana',
            'notes': 'Observações internas',
            'status': 'Status',
        }
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 4}),
            'must_have': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Separe por vírgula'}),
            'nice_to_have': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Separe por vírgula'}),
            'undesirable': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Separe por vírgula'}),
            'boolean_search': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'salary_min': forms.NumberInput(attrs={'min': 0}),
            'salary_max': forms.NumberInput(attrs={'min': 0}),
        }


class CandidateForm(forms.ModelForm):
    class Meta:
        model = Candidate
        fields = (
            'name',
            'current_title',
            'current_company',
            'location',
            'linkedin_url',
            'summary',
            'skills',
            'technologies',
            'languages',
            'certifications',
            'seniority',
            'experience_time',
            'average_tenure',
        )
        labels = {
            'name': 'Nome',
            'current_title': 'Cargo atual',
            'current_company': 'Empresa atual',
            'location': 'Localização',
            'linkedin_url': 'LinkedIn',
            'summary': 'Resumo',
            'skills': 'Skills',
            'technologies': 'Tecnologias',
            'languages': 'Idiomas',
            'certifications': 'Certificações',
            'seniority': 'Senioridade',
            'experience_time': 'Tempo de experiência (anos)',
            'average_tenure': 'Média de permanência (anos)',
        }
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 4}),
            'skills': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Separe por vírgula'}),
            'technologies': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Separe por vírgula'}),
            'languages': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ex: Ingles (Professional Working)'}),
            'certifications': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Separe por linha'}),
            'experience_time': forms.NumberInput(attrs={'step': '0.1', 'min': 0}),
            'average_tenure': forms.NumberInput(attrs={'step': '0.1', 'min': 0}),
        }
