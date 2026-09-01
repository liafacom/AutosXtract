"""Screening: dropping identity cards, with a measured margin."""

from __future__ import annotations

from autosxtract.quality.screening import assess, is_identity_document

TAX_CARD = (
    "MINISTERIO DA FAZENDA CADASTRO DE PESSOAS FISICAS NUMERO DE INSCRICAO "
    "123.456.789-00 CARTAO DE USO PESSOAL E INTRANSFERIVEL"
)
LEGITIMATE = (
    "ESCRITURA PUBLICA DE COMPRA E VENDA. Aos vinte dias do mes, perante mim "
    "escrivao, compareceram as partes qualificadas nos autos do processo em "
    "epigrafe, portadores de documento de identidade e inscritos no cadastro "
    "de pessoas fisicas, para lavrar a presente escritura de compra e venda "
    "do imovel objeto da matricula indicada, com alvara judicial deferido nos "
    "autos da execucao fiscal em tramite perante a vara civel desta comarca."
)


def test_a_tax_card_is_dropped():
    assert is_identity_document(TAX_CARD)


def test_a_legitimate_document_mentioning_identity_is_not_dropped():
    """A deed scores the same 2 marks as the card. Density is what separates."""
    assert not is_identity_document(LEGITIMATE)


def test_density_is_the_criterion_not_the_count():
    card = assess(TAX_CARD)
    document = assess(LEGITIMATE)
    assert card.density > document.density
    assert card.density >= 2.5 > document.density


def test_a_clearance_certificate_is_not_dropped():
    """``MINISTÉRIO DA FAZENDA`` is legitimate there — proof in a tax enforcement."""
    certificate = (
        "MINISTERIO DA FAZENDA SECRETARIA DA RECEITA FEDERAL CERTIDAO NEGATIVA "
        "DE DEBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E A DIVIDA ATIVA DA UNIAO. "
        "Ressalvado o direito de a Fazenda Nacional cobrar e inscrever "
        "quaisquer dividas de responsabilidade do sujeito passivo acima "
        "identificado que vierem a ser apuradas, e certificado que nao "
        "constam pendencias em seu nome, relativas a creditos tributarios "
        "administrados pela Secretaria da Receita Federal do Brasil."
    )
    assert not is_identity_document(certificate)


def test_a_vehicle_document_is_dropped():
    assert is_identity_document("CERTIFICADO DE REGISTRO DE VEICULO renavam 123")


def test_a_personal_attachment_with_short_text():
    """Catches the card the OCR read as loose names and codes, with no label."""
    loose = "ASSIN SILVIO MORAES DE SOUZA JUNIOR C2 80 CT T8LC66000"
    assert is_identity_document(loose, label="Documentos pessoais")


def test_the_label_alone_does_not_drop_a_long_document():
    """The label covers the BATCH; the size ceiling is what separates."""
    assert not is_identity_document(LEGITIMATE * 3, label="Documentos pessoais")


def test_the_verdict_carries_evidence():
    v = assess(TAX_CARD)
    assert v.drop
    assert "marks" in v.evidence
