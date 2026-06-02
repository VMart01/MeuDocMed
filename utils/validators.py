"""
Validadores brasileiros: CPF, registro profissional e verificacao via APIs dos
conselhos federais (CFM, COFEN, CFO, COFFITO, CFF).
"""
import re
import requests as http_requests

ESTADOS_BR = {
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA',
    'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN',
    'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
}


def validate_cpf(cpf: str) -> bool:
    cpf = re.sub(r'\D', '', cpf)
    if len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
        return False
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    if resto in (10, 11):
        resto = 0
    if resto != int(cpf[9]):
        return False
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    if resto in (10, 11):
        resto = 0
    return resto == int(cpf[10])


def clean_cpf(cpf: str) -> str:
    return re.sub(r'\D', '', cpf)


def validate_professional_registration(prof_type: str, registration: str) -> tuple:
    if prof_type == 'acs':
        if not validate_cpf(registration):
            return False, 'CPF invalido. ACS usam o CPF como identificacao.'
        return True, ''

    m = re.match(r'^([A-Z]+)/([A-Z]{2})-(\d+)$', registration.strip().upper())
    if not m:
        examples = {
            'medico': 'CRM/SP-123456', 'enfermeiro': 'COREN/RJ-654321',
            'dentista': 'CRO/MG-111222', 'farmaceutico': 'CRF/BA-333444',
            'fisioterapeuta': 'CREFITO/RS-555666',
        }
        return False, 'Formato invalido. Use o padrao {}.'.format(
            examples.get(prof_type, 'SIGLA/UF-NUMERO'))

    sigla, uf, _ = m.group(1), m.group(2), m.group(3)
    if uf not in ESTADOS_BR:
        return False, 'UF "{}" invalida.'.format(uf)

    expected = {
        'medico': 'CRM', 'enfermeiro': 'COREN', 'dentista': 'CRO',
        'farmaceutico': 'CRF', 'fisioterapeuta': 'CREFITO',
    }
    exp = expected.get(prof_type)
    if exp and sigla != exp:
        return False, 'Sigla esperada: {}. Recebido: {}.'.format(exp, sigla)
    return True, ''


def normalize_registration(prof_type: str, registration: str) -> str:
    if prof_type == 'acs':
        return clean_cpf(registration)
    return registration.strip().upper()


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _council_get(url: str):
    headers = {'Accept': 'application/json', 'User-Agent': 'MeuDocMed/1.0'}
    try:
        resp = http_requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _extract_first(data):
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        for key in ('results', 'data', 'items', 'registros'):
            val = data.get(key)
            if isinstance(val, list) and val:
                return val[0]
        return data
    return None


def _check_situacao(item: dict) -> tuple:
    ATIVOS = {'TRUE', '1', 'ATIVO', 'REGULAR', 'ACTIVE', 'HABILITADO'}
    INATIVOS = {'FALSE', '0', 'INATIVO', 'CANCELADO', 'SUSPENSO',
                'IRREGULAR', 'CASSADO', 'INACTIVE'}
    for key in ('situacao', 'status', 'ativo', 'situacaoRegistro'):
        raw = item.get(key)
        if raw is None:
            continue
        val = str(raw).upper().strip()
        if val in ATIVOS:
            return True, val
        if val in INATIVOS:
            return False, val
    return True, ''


def _nome_from_item(item: dict) -> str:
    for key in ('nome', 'name', 'nomeCompleto', 'nomeProfissional'):
        val = item.get(key, '')
        if val:
            return str(val).strip()
    return ''


# ---------------------------------------------------------------------------
# Verificadores por conselho
# ---------------------------------------------------------------------------

def verify_crm_cfm(numero: str, uf: str) -> tuple:
    data = _council_get(
        'https://portal.cfm.org.br/api/v1/medico/?crm={}&uf={}'.format(numero, uf.upper()))
    if data is None:
        return False, 'indisponivel'
    item = _extract_first(data)
    if not item:
        return False, 'CRM nao encontrado no CFM.'
    ativo, sit = _check_situacao(item)
    if not ativo:
        return False, 'CRM com situacao: {}.'.format(sit)
    return True, _nome_from_item(item) or 'Medico encontrado no CFM.'


def verify_coren_cofen(numero: str, uf: str) -> tuple:
    data = _council_get(
        'https://portal.cofen.gov.br/wp-json/api/v1/enfermeiros/?registro={}&uf={}'.format(
            numero, uf.upper()))
    if data is None:
        return False, 'indisponivel'
    item = _extract_first(data)
    if not item:
        return False, 'COREN nao encontrado no COFEN.'
    ativo, sit = _check_situacao(item)
    if not ativo:
        return False, 'COREN com situacao: {}.'.format(sit)
    return True, _nome_from_item(item) or 'Enfermeiro(a) encontrado(a) no COFEN.'


def verify_cro_cfo(numero: str, uf: str) -> tuple:
    data = _council_get(
        'https://cfo.org.br/wp-json/api/v1/inscricao?numero={}&uf={}'.format(
            numero, uf.upper()))
    if data is None:
        return False, 'indisponivel'
    item = _extract_first(data)
    if not item:
        return False, 'CRO nao encontrado no CFO.'
    ativo, sit = _check_situacao(item)
    if not ativo:
        return False, 'CRO com situacao: {}.'.format(sit)
    return True, _nome_from_item(item) or 'Dentista encontrado(a) no CFO.'


def verify_crefito_coffito(numero: str, uf: str) -> tuple:
    data = _council_get(
        'https://coffito.gov.br/nsite/api/fisioterapeuta?registro={}&uf={}'.format(
            numero, uf.upper()))
    if data is None:
        return False, 'indisponivel'
    item = _extract_first(data)
    if not item:
        return False, 'CREFITO nao encontrado no COFFITO.'
    ativo, sit = _check_situacao(item)
    if not ativo:
        return False, 'CREFITO com situacao: {}.'.format(sit)
    return True, _nome_from_item(item) or 'Fisioterapeuta encontrado(a) no COFFITO.'


def verify_crf_cff(numero: str, uf: str) -> tuple:
    data = _council_get(
        'https://cff.org.br/pharmanet/inscricao?crf={}&uf={}'.format(
            numero, uf.upper()))
    if data is None:
        return False, 'indisponivel'
    item = _extract_first(data)
    if not item:
        return False, 'CRF nao encontrado no CFF.'
    ativo, sit = _check_situacao(item)
    if not ativo:
        return False, 'CRF com situacao: {}.'.format(sit)
    return True, _nome_from_item(item) or 'Farmaceutico(a) encontrado(a) no CFF.'


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_COUNCIL_VERIFIERS = {
    'medico':         verify_crm_cfm,
    'enfermeiro':     verify_coren_cofen,
    'dentista':       verify_cro_cfo,
    'fisioterapeuta': verify_crefito_coffito,
    'farmaceutico':   verify_crf_cff,
}

_COUNCIL_NAMES = {
    'medico': 'CFM', 'enfermeiro': 'COFEN', 'dentista': 'CFO',
    'fisioterapeuta': 'COFFITO', 'farmaceutico': 'CFF',
}


def verify_council_registration(prof_type: str, registration: str) -> tuple:
    """
    Verifica o registro contra a API do conselho federal correspondente.
    Retorna (verificado, mensagem, indisponivel).
    ACS nao tem conselho externo: retorna (False, '', False).
    """
    verifier = _COUNCIL_VERIFIERS.get(prof_type)
    if verifier is None:
        return False, '', False

    m = re.match(r'^[A-Z]+/([A-Z]{2})-(\d+)$', registration.strip().upper())
    if not m:
        return False, 'Formato de registro inesperado.', False

    uf, numero = m.group(1), m.group(2)
    verified, msg = verifier(numero, uf)

    council = _COUNCIL_NAMES.get(prof_type, 'conselho')
    if msg == 'indisponivel':
        return False, 'API do {} indisponivel.'.format(council), True
    return verified, msg, False
