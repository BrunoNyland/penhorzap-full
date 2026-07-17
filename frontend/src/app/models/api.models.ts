/**
 * Tipos dos payloads/respostas da API (espelham os serializers em
 * www/api/serializers.py e www/api/views.py). Mantidos deliberadamente
 * "loose" onde o backend usa dicts sem serializer fixo -- o objetivo aqui é
 * dar autocomplete e pegar em build-time um rename de campo no backend que
 * quebraria o template, não modelar 100% das nuances do DRF.
 */

export interface BotConfig {
  ativo: boolean;
  ultima_atualizacao_dados: string | null;
  freshness_horas: number;
  debounce_segundos: number;
  horario_encerramento: string | null;
  responder_desconhecidos: boolean;
  dias_resgate_garantia: number;
  enviar_respostas_faq_ia: boolean;
  database_atualizada: boolean;
  atualizado_em: string;
}

export interface MensagensConfig {
  system_prompt: string;
  msg_saudacao: string;
  msg_saudacao_com_pedido: string;
  msg_cadastro_nao_localizado: string;
  msg_pedir_cpf: string;
  msg_cpf_invalido: string;
  msg_cpf_nao_bate: string;
  msg_db_desatualizada: string;
  msg_sem_contratos_ativos: string;
  msg_solicitacao_criada: string;
  msg_boleto_intro: string;
  msg_renovacao_proximo_vencimento: string;
  msg_quitacao_garantia: string;
  msg_segunda_via_confirma: string;
  msg_neutra_padrao: string;
  tpl_saudacao_cliente: string;
  tpl_saudacao_cliente_com_pedido: string;
  tpl_contrato_vencimento: string;
  tpl_contrato_renovacao: string;
  tpl_contrato_quitacao: string;
  tpl_contrato_parcela: string;
  tpl_contrato_resumo: string;
  tpl_contrato_laudo: string;
  tpl_lista_header: string;
  tpl_intro_vencimento: string;
  tpl_intro_renovacao: string;
  tpl_intro_quitacao: string;
  tpl_intro_parcela: string;
  tpl_intro_lista: string;
  tpl_intro_laudo: string;
  tpl_totalizador: string;
  tpl_totalizador_geral: string;
  msg_fallback_sem_resposta: string;
  msg_info_negada_desconhecido: string;
  msg_midia_nao_suportada: string;
  msg_duvida_anotada: string;
  msg_pedir_campo_valor_filtro: string;
  atualizado_em: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- restaurarMensagemCampo pode devolver o objeto inteiro com qualquer chave
  [key: string]: any;
}

export interface FAQResposta {
  id?: number;
  ordem: number;
  texto: string;
  arquivo?: string | null;
  arquivo_url?: string | null;
}

export interface FAQ {
  id: number;
  pergunta: string;
  ativo: boolean;
  respostas: FAQResposta[];
}

export interface FAQSugerida {
  id: number;
  pergunta: string;
  pergunta_original: string;
  conversa: number | null;
  ocorrencias: number;
  status: 'pendente' | 'aprovada' | 'rejeitada';
  faq_criada: number | null;
  revisado_por: number | null;
  revisado_por_nome: string;
  revisado_em: string | null;
  criado_em: string;
}

export interface Telefone {
  id: number;
  numero: string;
  numero_bruto: string;
}

export interface ContratoPenhorMini {
  contrato: string;
  situacao: string;
  situacao_codigo: string;
  vlr_liquido: string | number | null;
  vlr_parcela_atualizada: string | number | null;
  data_vencimento: string | null;
  atraso: number | null;
  laudo: string | null;
  peso: string | number | null;
  vlr_avaliacao: string | number | null;
  vlr_emprestimo: string | number | null;
}

export interface ClienteListItem {
  cpf: string;
  nome: string;
  cidade: string | null;
  bloqueado_ia: boolean;
  bloqueado_motivo: string | null;
  bloqueado_em: string | null;
  num_telefones: number;
  num_conversas: number;
  limite_especial: string | number | null;
  num_contratos_ativos: number;
  total_emprestimo_ativo: string | number;
  total_avaliacao_ativo: string | number;
}

export interface ClienteDetail {
  cpf: string;
  nome: string;
  situacao_cpf: string | null;
  situacao_cadastro: string | null;
  logradouro: string | null;
  bairro: string | null;
  cidade: string | null;
  cep: string | null;
  aniversario: string | null;
  bloqueado_ia: boolean;
  bloqueado_motivo: string | null;
  bloqueado_em: string | null;
  telefones: Telefone[];
  contratos_penhor: ContratoPenhorMini[];
  conversas: ConversaListItem[];
  solicitacoes: Solicitacao[];
}

export interface ConversaListItem {
  id: number;
  remote_jid: string;
  estado: string;
  tipo_contato: string;
  nome_salvo: string | null;
  cpf_verificado: string | null;
  precisa_revisao_humana: boolean;
  ultima_interacao: string;
  cliente_nome: string | null;
  cliente_cpf: string | null;
  num_contratos_ativos: number;
}

export interface MensagemPainel {
  id: number;
  direcao: 'in' | 'out';
  texto: string;
  wa_message_id: string | null;
  push_name: string | null;
  criado_em: string;
  possui_midia: boolean;
  tipo_midia: string;
  legenda: string;
  arquivo: string | null;
  enviado_ok: boolean;
}

export interface ConversaDetail {
  id: number;
  remote_jid: string;
  estado: string;
  tipo_contato: string;
  nome_salvo: string | null;
  cpf_verificado: string | null;
  precisa_revisao_humana: boolean;
  ultima_interacao: string;
  cliente: { cpf: string; nome: string; cidade: string | null } | null;
  mensagens: MensagemPainel[];
  solicitacoes: Solicitacao[];
}

export interface Boleto {
  id: number;
  arquivo: string;
  linha_digitavel: string | null;
  enviado_em: string | null;
  criado_em: string;
}

export interface Solicitacao {
  id: number;
  cliente: { cpf: string; nome: string; cidade: string | null } | null;
  conversa: number | null;
  tipo: string;
  escopo: string;
  contratos: ContratoPenhorMini[];
  status: string;
  resposta_ia: string | null;
  precisa_humano: boolean;
  boletos: Boleto[];
  historico_mensagens: MensagemPainel[];
  criado_em: string;
  atualizado_em: string;
}

export interface DashboardStats {
  por_tipo: { tipo: string; total: number; label: string }[];
  por_status: { status: string; total: number; label: string }[];
  serie_30_dias: { dia: string; recebidas: number; enviadas: number; conversas_novas: number; boletos_enviados: number }[];
  maior_valor_serie: number;
  total_clientes: number;
  clientes_com_telefone: number;
  clientes_com_conversa: number;
  clientes_bloqueados: number;
  total_solicitacoes: number;
  solicitacoes_precisa_humano: number;
  taxa_solicitacoes_humano: number;
  total_conversas: number;
  conversas_precisa_revisao: number;
  taxa_conversas_revisao: number;
  total_boletos: number;
  boletos_enviados: number;
  por_dia_semana: { label: string; total: number }[];
  maior_valor_semana: number;
  buckets_dia_mes: Record<string, number>;
  maior_valor_bucket: number;
  faqs_sugeridas_pendentes: number;
}

export interface WhatsappState {
  state: string;
  bot_ativo: boolean;
  qrcode_base64?: string | null;
}

export interface ImportJobStatus {
  id: number;
  status: 'pendente' | 'andamento' | 'concluido' | 'falhou';
  arquivo?: string;
  criado_em: string;
  finalizado_em?: string | null;
  erro?: string | null;
  counts?: Record<string, number>;
}
