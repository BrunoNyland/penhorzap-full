from django import forms
from django.forms import inlineformset_factory

from core.models import BotConfig, FAQ, FAQResposta, MensagensConfig


class FAQForm(forms.ModelForm):
    class Meta:
        model = FAQ
        fields = ["pergunta", "ativo"]
        widgets = {
            "pergunta": forms.TextInput(attrs={"class": "input", "maxlength": "255"}),
        }


FAQRespostaFormSet = inlineformset_factory(
    FAQ,
    FAQResposta,
    fields=["ordem", "texto", "arquivo"],
    extra=0,
    can_delete=True,
    widgets={
        "texto": forms.Textarea(attrs={"rows": 2, "class": "input", "maxlength": "1000"}),
        "ordem": forms.HiddenInput(),
    }
)


class MensagensConfigForm(forms.ModelForm):
    class Meta:
        model = MensagensConfig
        fields = [
            "system_prompt",
            "msg_saudacao",
            "msg_cadastro_nao_localizado",
            "msg_pedir_cpf",
            "msg_cpf_invalido",
            "msg_cpf_nao_bate",
            "msg_verificacao_ok",
            "msg_verificacao_falhou",
            "msg_sem_info_faq",
            "msg_db_desatualizada",
            "msg_sem_contratos_ativos",
            "msg_solicitacao_criada",
            "msg_boleto_intro",
            "msg_renovacao_proximo_vencimento",
            "msg_quitacao_garantia",
            "msg_segunda_via_confirma",
            "msg_insistiu_humano",
            "msg_neutra_padrao",
        ]
        widgets = {
            "system_prompt": forms.Textarea(attrs={"rows": 24, "class": "input"}),
            "msg_saudacao": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "msg_cadastro_nao_localizado": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_pedir_cpf": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_cpf_invalido": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_cpf_nao_bate": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_verificacao_ok": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_verificacao_falhou": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_sem_info_faq": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_db_desatualizada": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_sem_contratos_ativos": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_solicitacao_criada": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_boleto_intro": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_renovacao_proximo_vencimento": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_quitacao_garantia": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_segunda_via_confirma": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_insistiu_humano": forms.Textarea(attrs={"rows": 3, "class": "input"}),
            "msg_neutra_padrao": forms.Textarea(attrs={"rows": 3, "class": "input"}),
        }


class BotConfigForm(forms.ModelForm):
    class Meta:
        model = BotConfig
        fields = [
            "ativo",
            "horario_encerramento",
            "freshness_horas",
            "responder_desconhecidos",
            "dias_resgate_garantia",
        ]
        widgets = {
            "horario_encerramento": forms.TimeInput(attrs={"type": "time", "class": "input"}),
            "freshness_horas": forms.NumberInput(attrs={"class": "input", "min": 1}),
            "dias_resgate_garantia": forms.NumberInput(attrs={"class": "input", "min": 1}),
        }
