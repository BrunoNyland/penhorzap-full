import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  BotConfig,
  ClienteDetail,
  ClienteListItem,
  ConversaDetail,
  ConversaListItem,
  DashboardStats,
  FAQ,
  FAQSugerida,
  ImportJobStatus,
  MensagensConfig,
  Solicitacao,
  WhatsappState,
} from '../models/api.models';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private http = inject(HttpClient);

  // --- Dashboard ---
  getDashboardStats(): Observable<DashboardStats> {
    return this.http.get<DashboardStats>('/api/dashboard/');
  }

  // --- Configs ---
  getBotConfig(): Observable<BotConfig> {
    return this.http.get<BotConfig>('/api/configs/bot/');
  }

  updateBotConfig(data: Partial<BotConfig>): Observable<BotConfig> {
    return this.http.patch<BotConfig>('/api/configs/bot/', data);
  }

  getMensagensConfig(): Observable<MensagensConfig> {
    return this.http.get<MensagensConfig>('/api/configs/mensagens/');
  }

  updateMensagensConfig(data: Partial<MensagensConfig>): Observable<MensagensConfig> {
    return this.http.patch<MensagensConfig>('/api/configs/mensagens/', data);
  }

  restaurarMensagemCampo(campo: string): Observable<MensagensConfig> {
    return this.http.post<MensagensConfig>('/api/configs/mensagens/', { campo });
  }

  // --- FAQs ---
  getFAQs(): Observable<FAQ[]> {
    return this.http.get<FAQ[]>('/api/faqs/');
  }

  getFAQ(id: number): Observable<FAQ> {
    return this.http.get<FAQ>(`/api/faqs/${id}/`);
  }

  createFAQ(faqData: FormData | Partial<FAQ>): Observable<FAQ> {
    return this.http.post<FAQ>('/api/faqs/', faqData);
  }

  updateFAQ(id: number, faqData: FormData | Partial<FAQ>): Observable<FAQ> {
    return this.http.put<FAQ>(`/api/faqs/${id}/`, faqData);
  }

  deleteFAQ(id: number): Observable<void> {
    return this.http.delete<void>(`/api/faqs/${id}/`);
  }

  toggleFAQ(id: number): Observable<FAQ> {
    return this.http.post<FAQ>(`/api/faqs/${id}/toggle/`, {});
  }

  // --- Conversas ---
  getConversas(filters: { estado?: string; revisao?: string; q?: string; tipo_contato?: string } = {}): Observable<ConversaListItem[]> {
    let params = new HttpParams();
    if (filters.estado) params = params.set('estado', filters.estado);
    if (filters.revisao) params = params.set('revisao', filters.revisao);
    if (filters.q) params = params.set('q', filters.q);
    if (filters.tipo_contato) params = params.set('tipo_contato', filters.tipo_contato);
    return this.http.get<ConversaListItem[]>('/api/conversas/', { params });
  }

  getConversa(id: number): Observable<ConversaDetail> {
    return this.http.get<ConversaDetail>(`/api/conversas/${id}/`);
  }

  toggleConversaRevisao(id: number): Observable<{ precisa_revisao_humana: boolean }> {
    return this.http.post<{ precisa_revisao_humana: boolean }>(`/api/conversas/${id}/toggle-revisao/`, {});
  }

  limparTodasConversas(): Observable<void> {
    return this.http.post<void>('/api/conversas/limpar-todas/', { confirmacao: 'DELETAR_TUDO' });
  }

  enviarMensagemConversa(id: number, texto: string): Observable<ConversaDetail> {
    return this.http.post<ConversaDetail>(`/api/conversas/${id}/enviar/`, { texto });
  }

  enviarArquivoConversa(id: number, formData: FormData): Observable<ConversaDetail> {
    return this.http.post<ConversaDetail>(`/api/conversas/${id}/enviar-arquivo/`, formData);
  }

  // --- FAQs Sugeridas ---
  getFaqsSugeridas(statusParam?: string): Observable<FAQSugerida[]> {
    let params = new HttpParams();
    if (statusParam) params = params.set('status', statusParam);
    return this.http.get<FAQSugerida[]>('/api/faqs-sugeridas/', { params });
  }

  updateFaqSugerida(id: number, payload: Partial<FAQSugerida>): Observable<FAQSugerida> {
    return this.http.patch<FAQSugerida>(`/api/faqs-sugeridas/${id}/`, payload);
  }

  deleteFaqSugerida(id: number): Observable<void> {
    return this.http.delete<void>(`/api/faqs-sugeridas/${id}/`);
  }

  aprovarFaqSugerida(id: number, payload: { pergunta_final?: string; respostas: { ordem: number; texto: string }[] }): Observable<FAQSugerida> {
    return this.http.post<FAQSugerida>(`/api/faqs-sugeridas/${id}/aprovar/`, payload);
  }

  rejeitarFaqSugerida(id: number): Observable<FAQSugerida> {
    return this.http.post<FAQSugerida>(`/api/faqs-sugeridas/${id}/rejeitar/`, {});
  }

  // --- Clientes ---
  getClientes(filters: { q?: string; bloqueado?: string; ativos_somente?: string } = {}): Observable<ClienteListItem[]> {
    let params = new HttpParams();
    if (filters.q) params = params.set('q', filters.q);
    if (filters.bloqueado) params = params.set('bloqueado', filters.bloqueado);
    if (filters.ativos_somente) params = params.set('ativos_somente', filters.ativos_somente);
    return this.http.get<ClienteListItem[]>('/api/clientes/', { params });
  }

  getCliente(cpf: string): Observable<ClienteDetail> {
    return this.http.get<ClienteDetail>(`/api/clientes/${cpf}/`);
  }

  toggleClienteBloqueio(cpf: string, acao: 'bloquear' | 'desbloquear', motivo?: string): Observable<ClienteDetail> {
    return this.http.post<ClienteDetail>(`/api/clientes/${cpf}/toggle-bloqueio/`, { acao, motivo });
  }

  // --- WhatsApp Connection ---
  getWhatsappState(): Observable<WhatsappState> {
    return this.http.get<WhatsappState>('/api/whatsapp/state/');
  }

  toggleWhatsappBot(): Observable<WhatsappState> {
    return this.http.post<WhatsappState>('/api/whatsapp/state/', {});
  }

  // --- Simulator ---
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- estado do simulador é heterogêneo (turnos + debug da IA), não vale a pena modelar 1:1
  getSimulatorState(): Observable<any> {
    return this.http.get('/api/simulador/');
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  postSimulatorAction(payload: { acao: string; [key: string]: any }): Observable<any> {
    return this.http.post('/api/simulador/', payload);
  }

  // --- Solicitacoes / Boletos ---
  getSolicitacoes(statusParam?: string): Observable<Solicitacao[]> {
    let params = new HttpParams();
    if (statusParam) params = params.set('status', statusParam);
    return this.http.get<Solicitacao[]>('/api/solicitacoes/', { params });
  }

  uploadBoleto(solicitacaoId: number, formData: FormData): Observable<Solicitacao> {
    return this.http.post<Solicitacao>(`/api/solicitacoes/${solicitacaoId}/boletos/`, formData);
  }

  uploadSqlite(formData: FormData): Observable<ImportJobStatus> {
    return this.http.post<ImportJobStatus>('/api/import/sqlite/', formData);
  }

  getImportStatus(jobId: number): Observable<ImportJobStatus> {
    return this.http.get<ImportJobStatus>(`/api/import/sqlite/${jobId}/status/`);
  }

  getImportHistory(): Observable<ImportJobStatus[]> {
    return this.http.get<ImportJobStatus[]>('/api/import/sqlite/latest/');
  }
}
