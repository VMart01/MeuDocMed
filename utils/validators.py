"""
Validadores brasileiros: CPF e registro profissional.
"""
import re

ESTADOS_BR = {
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA',
    'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN',
    'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
}


def validate_cpf(cpf: str) -> bool:
    """
    Valida CPF usando o algoritmo oficial brasileiro.
    Aceita CPF com ou sem formatação (pontos e traço).
    """
    # Remove caracteres não numéricos
    cpf = re.sub(r'\D', '', cpf)

    if len(cpf) != 11:
        return False

    # Rejeita CPFs com todos os dígitos iguais (ex: 111.111.111-11)
    if cpf == cpf[0] * 11:
        return False

    # Valida primeiro dígito verificador
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    if resto == 10 or resto == 11:
        resto = 0
    if resto != int(cpf[9]):
        return False

    # Valida segundo dígito verificador
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    if resto == 10 or resto == 11:
        resto = 0
    if resto != int(cpf[10]):
        return False

    return True


def clean_cpf(cpf: str) -> str:
    """Remove formatação e retorna apenas os 11 dígitos."""
    return re.sub(r'\D', '', cpf)


def validate_professional_registration(prof_type: str, registration: str) -> tuple[bool, str]:
    """
    Valida o número de registro profissional.
    - ACS usa CPF como identificação.
    - Demais profissionais: SIGLA/UF-NUMERO (ex: CRM/SP-123456)

    Retorna (válido, mensagem_de_erro).
    """
    if prof_type == 'acs':
        if not validate_cpf(registration):
            return False, 'CPF inválido. Agentes Comunitários usam o CPF como identificação.'
        return True, ''

    # Padrão: SIGLA/UF-NUMERO
    # Aceita também SIGLA-UF-NUMERO ou SIGLA/UF NUMERO
    pattern = r'^([A-Z]+)/([A-Z]{2})-(\d+)$'
    m = re.match(pattern, registration.strip().upper())

    if not m:
        councils = {
            'medico': 'CRM/SP-123456',
            'enfermeiro': 'COREN/RJ-654321',
            'dentista': 'CRO/MG-111222',
            'farmaceutico': 'CRF/BA-333444',
            'fisioterapeuta': 'CREFITO/RS-555666',
        }
        example = councils.get(prof_type, 'SIGLA/UF-NUMERO')
        return False, f'Formato inválido. Use o padrão {example}.'

    sigla, uf, numero = m.group(1), m.group(2), m.group(3)

    if uf not in ESTADOS_BR:
        return False, f'UF "{uf}" inválida.'

    # Valida sigla esperada para cada tipo
    expected = {
        'medico': 'CRM',
        'enfermeiro': 'COREN',
        'dentista': 'CRO',
        'farmaceutico': 'CRF',
        'fisioterapeuta': 'CREFITO',
    }
    expected_sigla = expected.get(prof_type)
    if expected_sigla and sigla != expected_sigla:
        return False, f'Sigla esperada: {expected_sigla}. Recebido: {sigla}.'

    return True, ''


def normalize_registration(prof_type: str, registration: str) -> str:
    """Normaliza o registro para armazenamento (uppercase, sem espaços extras)."""
    if prof_type == 'acs':
        return clean_cpf(registration)
    return registration.strip().upper()
