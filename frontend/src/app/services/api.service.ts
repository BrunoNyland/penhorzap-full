import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private http = inject(HttpClient);

  // --- Dashboard ---
  getDashboardStats(): Observable<any> {
    return this.http.get('/api/dashboard/');
  }

  // --- Configs ---
  getBotConfig(): Observable<any> {
    return this.http.get('/api/configs/bot/');
  }

  updateBotConfig(data: any): Observable<any> {
    return this.http.patch('/api/configs/bot/', data);
  }

  getMensagensConfig(): Observable<any> {
    return this.http.get('/api/configs/mensagens/');
  }

  updateMensagensConfig(data: any): Observable<any> {
    return this.http.patch('/api/configs/mensagens/', data);
  }

  restaurarMensagemCampo(campo: string): Observable<any> {
    return this.http.post('/api/configs/mensagens/', { campo });
  }

  // --- FAQs ---
  getFAQs(): Observable<any[]> {
    return this.http.get<any[]>('/api/faqs/');
  }

  getFAQ(id: number): Observable<any> {
    return this.http.get(`/api/faqs/${id}/`);
  }

  createFAQ(faqData: FormData | any): Observable<any> {
    return this.http.post('/api/faqs/', faqData);
  }

  updateFAQ(id: number, faqData: FormData | any): Observable<any> {
    return this.http.put(`/api/faqs/${id}/`, faqData);
  }

  deleteFAQ(id: number): Observable<any> {
    return this.http.delete(`/api/faqs/${id}/`);
  }

  toggleFAQ(id: number): Observable<any> {
    return this.http.post(`/api/faqs/${id}/toggle/`, {});
  }

  // --- Conversas ---
  getConversas(filters: { estado?: string; revisao?: string; q?: string } = {}): Observable<any[]> {
    let params = new HttpParams();
    if (filters.estado) params = params.set('estado', filters.estado);
    if (filters.revisao) params = params.set('revisao', filters.revisao);
    if (filters.q) params = params.set('q', filters.q);
    return this.http.get<any[]>('/api/conversas/', { params });
  }

  getConversa(id: number): Observable<any> {
    return this.http.get(`/api/conversas/${id}/`);
  }

  toggleConversaRevisao(id: number): Observable<any> {
    return this.http.post(`/api/conversas/${id}/toggle-revisao/`, {});
  }

  // --- Clientes ---
  getClientes(filters: { q?: string; bloqueado?: string } = {}): Observable<any[]> {
    let params = new HttpParams();
    if (filters.q) params = params.set('q', filters.q);
    if (filters.bloqueado) params = params.set('bloqueado', filters.bloqueado);
    return this.http.get<any[]>('/api/clientes/', { params });
  }

  getCliente(cpf: string): Observable<any> {
    return this.http.get(`/api/clientes/${cpf}/`);
  }

  toggleClienteBloqueio(cpf: string, acao: 'bloquear' | 'desbloquear', motivo?: string): Observable<any> {
    return this.http.post(`/api/clientes/${cpf}/toggle-bloqueio/`, { acao, motivo });
  }

  // --- WhatsApp Connection ---
  getWhatsappState(): Observable<any> {
    return this.http.get('/api/whatsapp/state/');
  }

  toggleWhatsappBot(): Observable<any> {
    return this.http.post('/api/whatsapp/state/', {});
  }

  // --- Simulator ---
  getSimulatorState(): Observable<any> {
    return this.http.get('/api/simulador/');
  }

  postSimulatorAction(payload: { acao: string; [key: string]: any }): Observable<any> {
    return this.http.post('/api/simulador/', payload);
  }

  // --- Solicitacoes / Boletos ---
  getSolicitacoes(statusParam?: string): Observable<any[]> {
    let params = new HttpParams();
    if (statusParam) params = params.set('status', statusParam);
    return this.http.get<any[]>('/api/solicitacoes/', { params });
  }

  uploadBoleto(solicitacaoId: number, formData: FormData): Observable<any> {
    return this.http.post(`/api/solicitacoes/${solicitacaoId}/boletos/`, formData);
  }
}
