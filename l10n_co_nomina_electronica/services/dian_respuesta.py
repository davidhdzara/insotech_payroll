# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""Interpretación de las respuestas de la DIAN (parte A: helpers puros).

Python puro, SIN dependencias de Odoo (convención de ``services/``). Estos 4 helpers vivían en
``models/l10n_co_ne_documento_mixin.py`` y no leen ningún campo del recibo; se extraen aquí para que
el recibo (mixin) y el documento mensual interpreten la respuesta con UNA sola implementación (doc 53
§23.12, decisión de Tech Lead: dos copias del parseo de respuestas ya causaron el incidente DIAN del
2026-09-14).

El mixin conserva sus 4 nombres (``_ne_response_text``, ``_ne_cune_candidates``,
``_ne_number_candidates``, ``_ne_is_set_level_status``) como envoltorios delgados que llaman aquí:
el comportamiento del recibo no cambia.
"""

from . import soap_client

# Tope del resumen que se guarda en el formulario (la evidencia completa vive en l10n.co.ne.exchange).
LIMITE_TEXTO_RESPUESTA = 5000


def texto_respuesta(value, limite=LIMITE_TEXTO_RESPUESTA):
    """Resumen de texto de un sobre SOAP/ZIP de respuesta, recortado a ``limite`` caracteres.

    AUD-DIAN-34 (2026-10-04): este texto es un resumen para la vista, no evidencia -- la evidencia
    completa (sobre SOAP y ZIP de respuesta íntegros, sin truncar) vive en l10n.co.ne.exchange. Un
    SendTestSetAsync de 4 nóminas puede traer un ZIP base64 de varios MB; guardarlo entero en el
    registro lo infla sin necesidad.

    ``bytes`` se decodifica como utf-8 con ``errors='replace'``; ``None`` o vacío devuelve ''.
    """
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    return (value or '')[:limite]


def candidatos_cune(result):
    """Candidatos de CUNE de un resultado, sin confundirlos con IDs SOAP.

    AUD-DIAN-34 (2026-10-04): evidencia real (GetStatusZip AUTORIZADO, nómina SME-10) confirma que
    el CUNE del documento original viaja en
    ``cac:DocumentResponse/cac:DocumentReference/cbc:UUID`` dentro del ApplicationResponse -- ver
    ``soap_client.extract_document_cunes``.

    Args:
        result: dict de un resultado de la DIAN (claves ``XmlDocumentKey``, ``CUNE``,
            ``DocumentKey`` y ``ApplicationResponse``).

    Returns:
        ``set`` de str (cada valor de clave sin espacios en los extremos).
    """
    candidates = set()
    for key in ('XmlDocumentKey', 'CUNE', 'DocumentKey'):
        value = result.get(key)
        if value:
            candidates.add(value.strip())
    application = result.get('ApplicationResponse') or ''
    if application:
        candidates.update(soap_client.extract_document_cunes(application))
    return candidates


def candidatos_numero(result):
    """NÚMERO de negocio del documento original (no es CUNE).

    ``cac:DocumentResponse/cac:DocumentReference/cbc:ID`` -- solo se usa como respaldo cuando la
    DIAN no entrega CUNE (ver ``soap_client.extract_document_numbers``).

    Returns:
        ``set`` de str; vacío si el resultado no trae ``ApplicationResponse``.
    """
    application = result.get('ApplicationResponse') or ''
    if not application:
        return set()
    return soap_client.extract_document_numbers(application)


def es_respuesta_de_set(response):
    """True si la respuesta de GetStatusZip es sobre el SET de pruebas completo, no sobre el
    documento individual consultado.

    H-012 (2026-10-06): evidencia real (NA0000000049, payslip 944, ZipKey 98e2fdc3) -- GetStatusZip
    respondió StatusCode="2", IsValid="false", StatusDescription="Set de prueba con identificador
    e07c1748... se encuentra Aceptado.", sin XmlDocumentKey ni ApplicationResponse (ningún dato que
    identifique el documento). Esa combinación (StatusCode 2 + IsValid false + cero datos de
    documento) es la FORMA de una respuesta de nivel set, no una hipótesis sobre por qué la DIAN
    respondió así -- no se asume la causa (Tech Lead: "mi hipótesis no está confirmada, el fix no
    debe depender de ella").

    ``IsValid`` se compara en minúsculas ('true', 'True' y 'TRUE' son lo mismo).
    """
    if str(response.get('StatusCode', '')).strip() != '2':
        return False
    if str(response.get('IsValid', '')).lower() == 'true':
        return False
    return not response.get('XmlDocumentKey') and not response.get('ApplicationResponse')
