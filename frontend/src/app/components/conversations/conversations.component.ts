import { Component, inject, signal, computed, OnInit, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePipe, NgClass } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { IconComponent } from '../../shared/icon/icon.component';

@Component({
  selector: 'app-conversations',
  standalone: true,
  imports: [FormsModule, DatePipe, NgClass, IconComponent],
  template: `
    <div class="conversa-layout" [class.has-selected-chat]="selectedChatId() !== null">
      <!-- Left Panel: Chat List -->
      <div class="chat-list-panel card">
        <div class="panel-header">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <h2>Atendimentos</h2>
            <button 
              class="btn btn-icon" 
              (click)="limparConversas()" 
              title="Apagar permanentemente todas as conversas"
              style="padding: 4px; display: flex; align-items: center; justify-content: center; background: transparent; border: none; cursor: pointer; color: #dc3545;"
            >
              <app-icon name="trash" [size]="18"></app-icon>
            </button>
          </div>
          <p class="text-muted">Filtragem e controle de revisão humana</p>
          
          <div class="filter-controls margin-top-sm">
            <input 
              type="text" 
              placeholder="Buscar por JID, CPF ou Nome..." 
              [(ngModel)]="searchQuery" 
              (ngModelChange)="loadConversas()"
            />
            
            <div class="grid-2 margin-top-sm">
              <select [(ngModel)]="filterEstado" (change)="loadConversas()">
                <option value="">Todos os Estados</option>
                <option value="nova">Nova</option>
                <option value="aguardando_verificacao">Aguardando Verificação</option>
                <option value="verificada">Verificada</option>
                <option value="intencao_capturada">Intenção Capturada</option>
                <option value="aguardando_boleto">Aguardando Boleto</option>
                <option value="boleto_enviado">Boleto Enviado</option>
                <option value="encerrada">Encerrada</option>
              </select>
              
              <button 
                class="btn btn-secondary btn-small" 
                [class.btn-active]="filterRevisao() === '1'"
                (click)="toggleRevisaoFilter()"
              >
                <app-icon name="flag" [size]="14"></app-icon> Só Revisão
              </button>
            </div>
          </div>
        </div>

        <div class="chat-items-list margin-top">
          @if (loadingChats()) {
            <div class="list-placeholder">
              <div class="spinner spinner-small"></div>
              <span>Carregando conversas...</span>
            </div>
          } @else {
            @for (chat of conversas(); track chat.id) {
              <div 
                class="chat-item" 
                [class.active]="selectedChatId() === chat.id" 
                [class.needs-review]="chat.precisa_revisao_humana"
                (click)="selectChat(chat.id)"
              >
                <div class="chat-item-header flex justify-between">
                  <strong>{{ getDisplayName(chat) }}</strong>
                  <span class="chat-time">{{ formatTime(chat.ultima_interacao) }}</span>
                </div>
                <div class="chat-item-body flex justify-between align-center margin-top-xs">
                  <span class="chat-jid text-muted">{{ formatJid(chat.remote_jid) }}</span>
                  <span class="badge badge-sm" [ngClass]="getTipoContatoBadgeClass(chat.tipo_contato)">
                    {{ getTipoContatoDisplay(chat.tipo_contato) }}
                  </span>
                </div>
                @if (chat.cliente_cpf) {
                  <div class="chat-item-cliente text-muted">
                    <span class="text-small">CPF: <strong>{{ chat.cliente_cpf }}</strong></span>
                    @if (chat.num_contratos_ativos > 0) {
                      <span class="badge badge-sm badge-success margin-left-xs">{{ chat.num_contratos_ativos }} contrato(s)</span>
                    }
                  </div>
                }
                <div class="chat-item-states flex gap-2 margin-top-xs">
                  <span class="badge badge-sm" [ngClass]="getStateBadgeClass(chat.estado)">
                    {{ getStateDisplay(chat.estado) }}
                  </span>
                  @if (chat.precisa_revisao_humana) {
                    <span class="badge badge-sm badge-danger"><app-icon name="flag" [size]="10"></app-icon> Revisão</span>
                  }
                </div>
              </div>
            } @empty {
              <p class="text-muted text-center" style="padding: 24px;">Nenhuma conversa localizada.</p>
            }
          }
        </div>
      </div>

      <!-- Right Panel: Message Details -->
      <div class="chat-details-panel card">
        @if (loadingDetails()) {
          <div class="details-placeholder">
            <div class="spinner"></div>
            <p>Carregando histórico do chat...</p>
          </div>
        } @else if (activeChat()) {
          <!-- Back button for mobile -->
          <button class="btn btn-secondary back-button margin-bottom-sm" (click)="clearSelection()">
            <app-icon name="arrow-left" [size]="14"></app-icon> Voltar para Atendimentos
          </button>
          
          <!-- Chat Header -->
          <div class="detail-header flex align-center justify-between">
            <div>
              <h3>{{ getDisplayName(activeChat()) }}</h3>
              <p class="text-muted text-small">
                {{ formatJid(activeChat().remote_jid) }}
                <span class="badge badge-sm margin-left-xs" [ngClass]="getTipoContatoBadgeClass(activeChat().tipo_contato)">
                  {{ getTipoContatoDisplay(activeChat().tipo_contato) }}
                </span>
                <span class="badge badge-sm margin-left-xs" [ngClass]="getStateBadgeClass(activeChat().estado)">
                  {{ getStateDisplay(activeChat().estado) }}
                </span>
              </p>
              @if (activeChat().cliente) {
                <p class="text-muted text-small">
                  Cliente: <strong>{{ activeChat().cliente.nome }}</strong> • CPF: {{ activeChat().cliente.cpf }}
                </p>
              } @else if (!activeChat().nome_salvo) {
                <p class="text-muted text-small">Contato não identificado (sem nome salvo).</p>
              } @else {
                <p class="text-muted text-small">{{ activeChat().nome_salvo }}</p>
              }
            </div>
            
            <div class="flex gap-2">
              <button 
                class="btn" 
                [class.btn-danger]="!activeChat().precisa_revisao_humana" 
                [class.btn-secondary]="activeChat().precisa_revisao_humana"
                (click)="toggleRevisao(activeChat().id)"
              >
                @if (activeChat().precisa_revisao_humana) {
                  <app-icon name="check" [size]="14"></app-icon> Concluir Revisão
                } @else {
                  <app-icon name="flag" [size]="14"></app-icon> Marcar para Revisão
                }
              </button>
            </div>
          </div>

          <!-- Message History -->
          <div class="messages-viewport" #messagesContainer>
            @for (msg of activeChat().mensagens; track msg.id) {
              <div class="message-wrapper" [class.incoming]="msg.direcao === 'in'">
                <div class="message-balloon">
                  @if (msg.possui_midia) {
                    <div class="message-media">
                      @if (msg.tipo_midia === 'image') {
                        <a [href]="'/api/conversas/' + activeChat().id + '/mensagens/' + msg.id + '/media/'" target="_blank">
                          <img [src]="'/api/conversas/' + activeChat().id + '/mensagens/' + msg.id + '/media/'" alt="Imagem" class="chat-media-image" />
                        </a>
                        @if (msg.legenda) {
                          <div class="message-text margin-top-xs">{{ msg.legenda }}</div>
                        }
                      } @else if (msg.tipo_midia === 'audio') {
                        <audio controls [src]="'/api/conversas/' + activeChat().id + '/mensagens/' + msg.id + '/media/'" class="chat-media-audio"></audio>
                      } @else if (msg.tipo_midia === 'video') {
                        <video controls [src]="'/api/conversas/' + activeChat().id + '/mensagens/' + msg.id + '/media/'" class="chat-media-video"></video>
                      } @else if (msg.tipo_midia === 'document') {
                        <a [href]="'/api/conversas/' + activeChat().id + '/mensagens/' + msg.id + '/media/'" target="_blank" download class="chat-media-document">
                          <app-icon name="file-text" [size]="18"></app-icon>
                          <span>{{ msg.legenda || 'Baixar Documento' }}</span>
                        </a>
                      }
                    </div>
                  } @else {
                    <div class="message-text">{{ msg.texto }}</div>
                  }
                  <div class="message-time text-muted">{{ msg.criado_em | date:'HH:mm' }}</div>
                </div>
              </div>
            } @empty {
              <p class="text-muted text-center" style="padding: 48px;">Histórico de mensagens vazio.</p>
            }
          </div>

          <!-- Reply Box -->
          <div class="reply-box">
            <textarea
              #respostaInput
              placeholder="Digite uma resposta para {{ getDisplayName(activeChat()) }}..."
              [(ngModel)]="respostaTexto"
              (keydown.enter.prevent)="!enviando() && respostaTexto.trim() && enviarResposta()"
              rows="2"
            ></textarea>
            <button
              class="btn btn-primary btn-small"
              [disabled]="enviando() || !respostaTexto.trim()"
              (click)="enviarResposta()"
            >
              @if (enviando()) {
                <div class="spinner spinner-small"></div>
              } @else {
                <app-icon name="send" [size]="14"></app-icon> Enviar
              }
            </button>
          </div>

          <!-- Solicitacoes & Boleto Upload Section -->
          <div class="solicitacoes-section">
            <h4>Solicitações neste atendimento</h4>
            
            <div class="solicitacoes-list margin-top-xs">
              @for (sol of activeChat().solicitacoes; track sol.id) {
                <div class="sol-card card">
                  <div class="sol-header flex justify-between align-center">
                    <strong>Solicitação #{{ sol.id }} - {{ getSolTipoDisplay(sol.tipo) }}</strong>
                    <span class="badge" [ngClass]="getSolStatusBadgeClass(sol.status)">
                      {{ getSolStatusDisplay(sol.status) }}
                    </span>
                  </div>
                  
                  <div class="sol-body margin-top-xs">
                    <p class="text-muted text-small">
                      Tipo: {{ sol.escopo === 'todos' ? 'Todos os contratos' : 'Contratos específicos' }}
                      • Criado em: {{ sol.criado_em | date:'dd/MM/yyyy HH:mm' }}
                    </p>
                    
                    @if (sol.precisa_humano) {
                      <div class="badge badge-warning margin-top-xs">IA encaminhou para operador</div>
                    }

                    <!-- Listed Boletos -->
                    @if (sol.boletos && sol.boletos.length > 0) {
                      <div class="boletos-list margin-top-xs">
                        <strong>Boletos Enviados:</strong>
                        <ul>
                          @for (bol of sol.boletos; track bol.id) {
                            <li>
                              <app-icon name="file-text" [size]="14"></app-icon> <a [href]="bol.arquivo" target="_blank" class="text-success">Ver PDF</a>
                              @if (bol.linha_digitavel) {
                                <br/><code class="text-small">{{ bol.linha_digitavel }}</code>
                              }
                            </li>
                          }
                        </ul>
                      </div>
                    }

                    <!-- Upload Form (visible only if status is PENDENTE) -->
                    @if (sol.status === 'pendente') {
                      <div class="upload-boleto-form card margin-top">
                        <h5 class="flex align-center gap-2"><app-icon name="send" [size]="14"></app-icon> Enviar Boleto para o Cliente</h5>
                        <form (ngSubmit)="enviarBoleto(sol.id)">
                          <div class="grid-2 margin-top-xs">
                            <div class="form-group">
                              <label>Arquivo PDF do Boleto</label>
                              <input 
                                type="file" 
                                accept="application/pdf" 
                                required
                                (change)="onBoletoFileSelected($event, sol.id)"
                              />
                            </div>
                            <div class="form-group">
                              <label>Linha Digitável (Opcional)</label>
                              <input 
                                type="text" 
                                placeholder="Digite a linha digitável..."
                                [(ngModel)]="boletoLinhas[sol.id]"
                                name="linha_digitavel"
                              />
                            </div>
                          </div>
                          <button 
                            type="submit" 
                            class="btn btn-primary btn-small margin-top-xs"
                            [disabled]="uploadingBoletoId() === sol.id || !boletoFiles[sol.id]"
                          >
                            {{ uploadingBoletoId() === sol.id ? 'Processando...' : 'Enviar Boleto ao WhatsApp' }}
                          </button>
                        </form>
                      </div>
                    }
                  </div>
                </div>
              } @empty {
                <p class="text-muted text-small">Nenhuma solicitação financeira criada pelo robô para este cliente.</p>
              }
            </div>
          </div>
        } @else {
          <div class="details-placeholder">
            <p>Selecione um atendimento na lista lateral para visualizar a conversa</p>
          </div>
        }
      </div>
    </div>
  `,
  styles: [`
    .conversa-layout {
      display: flex;
      gap: 24px;
      height: calc(100vh - 120px);
    }
    .chat-list-panel {
      width: 320px;
      display: flex;
      flex-direction: column;
      padding: 16px;
      flex-shrink: 0;
    }
    .chat-details-panel {
      flex: 1;
      display: flex;
      flex-direction: column;
      padding: 24px;
      overflow-y: auto;
    }
    .panel-header h2 {
      font-size: 20px;
      margin-bottom: 2px;
    }
    .margin-top-xs { margin-top: 6px; }
    .margin-top-sm { margin-top: 10px; }
    .btn-active {
      background-color: var(--color-danger);
      color: white;
      border-color: var(--color-danger);
    }
    .chat-items-list {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .chat-item {
      padding: 12px;
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      cursor: pointer;
      transition: all var(--transition-fast);
      background-color: var(--bg-primary);
      position: relative;
    }
    .chat-item:hover {
      border-color: var(--color-accent);
    }
    .chat-item.active {
      border-color: var(--color-accent);
      background-color: var(--bg-surface);
    }
    .chat-item.needs-review {
      border-left: 4px solid var(--color-danger);
    }
    .chat-time {
      font-size: 11px;
      color: var(--text-muted);
    }
    .chat-jid {
      font-size: 12px;
      max-width: 170px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
.chat-item-cliente {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
      margin-top: 2px;
    }
.chat-item-states {
      flex-wrap: wrap;
    }
.badge-sm {
      font-size: 10px;
      padding: 2px 6px;
    }
    .review-indicator {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      color: var(--color-danger);
      font-weight: 600;
      margin-top: 4px;
    }
    .list-placeholder, .details-placeholder {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      flex: 1;
      color: var(--text-muted);
      gap: 12px;
    }
    .detail-header {
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border-color);
    }
    .detail-header h3 {
      font-size: 20px;
    }
    .messages-viewport {
      flex: 1;
      min-height: 250px;
      max-height: 450px;
      overflow-y: auto;
      padding: 16px;
      background-color: var(--bg-primary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin: 18px 0;
    }
    .message-wrapper {
      display: flex;
      width: 100%;
    }
    .message-wrapper.incoming {
      justify-content: flex-start;
    }
    .message-wrapper:not(.incoming) {
      justify-content: flex-end;
    }
    .message-balloon {
      max-width: 75%;
      padding: 10px 14px;
      border-radius: var(--radius-md);
      font-size: 14px;
      line-height: 1.4;
      position: relative;
    }
    .message-wrapper.incoming .message-balloon {
      background-color: var(--bg-surface);
      color: var(--text-primary);
      border-bottom-left-radius: 2px;
    }
    .message-wrapper:not(.incoming) .message-balloon {
      background-color: var(--color-accent);
      color: white;
      border-bottom-right-radius: 2px;
    }
    .message-time {
      font-size: 10px;
      text-align: right;
      margin-top: 4px;
    }
    .message-wrapper:not(.incoming) .message-time {
      color: rgba(255, 255, 255, 0.7);
    }
    .solicitacoes-section {
      border-top: 1px solid var(--border-color);
      padding-top: 18px;
    }
    .sol-card {
      background-color: var(--bg-primary);
      border-color: var(--border-color);
      padding: 16px;
      margin-bottom: 12px;
    }
    .upload-boleto-form {
      background-color: var(--bg-secondary);
      border: 1px solid var(--border-color);
      padding: 16px;
    }
    .upload-boleto-form h5 {
      font-size: 13px;
      font-weight: 600;
    }
.reply-box {
      display: flex;
      gap: 10px;
      padding: 12px 0 0 0;
      align-items: flex-end;
    }
.reply-box textarea {
      flex: 1;
      padding: 10px 12px;
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      background-color: var(--bg-primary);
      color: var(--text-primary);
      font-family: inherit;
      font-size: 14px;
      resize: vertical;
      min-height: 48px;
    }
.reply-box textarea:focus {
      outline: none;
      border-color: var(--color-accent);
    }
.reply-box button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
      min-width: 100px;
      justify-content: center;
    }
.reply-box .spinner-small {
      width: 16px;
      height: 16px;
      border-width: 2px;
    }
    .boletos-list ul {
      padding-left: 20px;
      margin-top: 4px;
    }
    .spinner-small {
      width: 20px;
      height: 20px;
      border-width: 2px;
    }
    .chat-media-image {
      max-width: 100%;
      max-height: 300px;
      border-radius: var(--radius-sm);
      cursor: pointer;
      display: block;
      margin-bottom: 4px;
    }
    .chat-media-audio {
      max-width: 260px;
      display: block;
    }
    .chat-media-video {
      max-width: 100%;
      max-height: 300px;
      border-radius: var(--radius-sm);
      display: block;
    }
    .chat-media-document {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      background: rgba(0, 0, 0, 0.05);
      border-radius: var(--radius-sm);
      text-decoration: none;
      color: var(--text-primary);
      transition: background var(--transition-fast);
    }
    .chat-media-document:hover {
      background: rgba(0, 0, 0, 0.1);
    }
    .message-wrapper:not(.incoming) .chat-media-document {
      background: rgba(255, 255, 255, 0.15);
      color: white;
    }
    .message-wrapper:not(.incoming) .chat-media-document:hover {
      background: rgba(255, 255, 255, 0.25);
    }
    .chat-media-document span {
      text-decoration: underline;
      font-size: 13px;
    }
    
    /* Responsive Styling for Mobile */
    .back-button {
      display: none;
    }

    @media (max-width: 768px) {
      .conversa-layout {
        flex-direction: column;
        height: calc(100vh - 120px) !important;
        gap: 0 !important;
      }
      .chat-list-panel {
        width: 100% !important;
        display: flex !important;
        height: 100%;
      }
      .chat-details-panel {
        display: none !important;
      }
      .conversa-layout.has-selected-chat .chat-list-panel {
        display: none !important;
      }
      .conversa-layout.has-selected-chat .chat-details-panel {
        width: 100% !important;
        display: flex !important;
        padding: 16px !important;
        height: 100%;
      }
      .back-button {
        display: inline-flex !important;
        align-items: center;
        gap: 6px;
      }
      .detail-header {
        flex-direction: column;
        align-items: flex-start !important;
        gap: 12px;
      }
      .reply-box {
        padding: 12px 0;
      }
      .chat-media-image, .chat-media-video {
        max-height: 200px;
      }
    }
  `]
})
export class ConversationsComponent implements OnInit, OnDestroy {
  private apiService = inject(ApiService);

  conversas = signal<any[]>([]);
  activeChat = signal<any | null>(null);

  loadingChats = signal(false);
  loadingDetails = signal(false);
  uploadingBoletoId = signal<number | null>(null);
  enviando = signal(false);

  searchQuery = '';
  filterEstado = '';
  filterRevisao = signal<'0' | '1'>('0');
  respostaTexto = '';

  // Boleto upload form state helper maps
  boletoFiles: { [solicitacaoId: number]: File } = {};
  boletoLinhas: { [solicitacaoId: number]: string } = {};

  selectedChatId = signal<number | null>(null);
  private pollingInterval: any;

  ngOnInit(): void {
    this.loadConversas();
    // Setup polling every 8 seconds to fetch new incoming messages dynamically
    this.pollingInterval = setInterval(() => {
      this.loadConversas(true);
      if (this.selectedChatId()) {
        this.loadActiveChatDetails(this.selectedChatId()!, true);
      }
    }, 8000);
  }

  ngOnDestroy(): void {
    if (this.pollingInterval) {
      clearInterval(this.pollingInterval);
    }
  }

  loadConversas(silent = false): void {
    if (!silent) this.loadingChats.set(true);
    this.apiService.getConversas({
      estado: this.filterEstado,
      revisao: this.filterRevisao(),
      q: this.searchQuery
    }).subscribe({
      next: (data) => {
        this.conversas.set(data);
        this.loadingChats.set(false);
      },
      error: () => this.loadingChats.set(false)
    });
  }

  toggleRevisaoFilter(): void {
    this.filterRevisao.update(v => v === '0' ? '1' : '0');
    this.loadConversas();
  }

  selectChat(id: number): void {
    this.selectedChatId.set(id);
    this.loadActiveChatDetails(id);
  }

  clearSelection(): void {
    this.selectedChatId.set(null);
    this.activeChat.set(null);
  }

  loadActiveChatDetails(id: number, silent = false): void {
    if (!silent) this.loadingDetails.set(true);
    this.apiService.getConversa(id).subscribe({
      next: (data) => {
        this.activeChat.set(data);
        this.loadingDetails.set(false);
      },
      error: () => this.loadingDetails.set(false)
    });
  }

  toggleRevisao(id: number): void {
    this.apiService.toggleConversaRevisao(id).subscribe({
      next: (res) => {
        if (this.activeChat() && this.activeChat().id === id) {
          this.activeChat.update(chat => ({ ...chat, precisa_revisao_humana: res.precisa_revisao_humana }));
        }
        // Refresh conversations list to update indicators
        this.loadConversas(true);
      }
    });
  }

  limparConversas(): void {
    const confirmacao = confirm('⚠️ Atenção: Esta ação irá apagar permanentemente TODAS as conversas e históricos de mensagens. Deseja continuar?');
    if (confirmacao) {
      this.apiService.limparTodasConversas().subscribe({
        next: () => {
          this.clearSelection();
          this.loadConversas();
          alert('Histórico de conversas limpo com sucesso!');
        },
        error: (err) => {
          alert('Erro ao limpar histórico de conversas: ' + (err.error?.detail || err.message));
        }
      });
    }
  }

  enviarResposta(): void {
    const texto = this.respostaTexto.trim();
    const chatId = this.selectedChatId();
    if (!texto || !chatId || this.enviando()) return;

    this.enviando.set(true);
    this.apiService.enviarMensagemConversa(chatId, texto).subscribe({
      next: () => {
        this.enviando.set(false);
        this.respostaTexto = '';
        this.loadActiveChatDetails(chatId, true);
      },
      error: () => this.enviando.set(false)
    });
  }

  onBoletoFileSelected(event: any, solicitacaoId: number): void {
    const file = event.target.files[0];
    if (file) {
      this.boletoFiles[solicitacaoId] = file;
    }
  }

  enviarBoleto(solicitacaoId: number): void {
    const file = this.boletoFiles[solicitacaoId];
    if (!file) return;

    this.uploadingBoletoId.set(solicitacaoId);
    
    const formData = new FormData();
    formData.append('arquivo', file);
    if (this.boletoLinhas[solicitacaoId]) {
      formData.append('linha_digitavel', this.boletoLinhas[solicitacaoId]);
    }

    this.apiService.uploadBoleto(solicitacaoId, formData).subscribe({
      next: () => {
        this.uploadingBoletoId.set(null);
        // Clear form values
        delete this.boletoFiles[solicitacaoId];
        delete this.boletoLinhas[solicitacaoId];
        // Reload details to show the updated status & boleto list
        if (this.selectedChatId()) {
          this.loadActiveChatDetails(this.selectedChatId()!);
        }
      },
      error: () => {
        this.uploadingBoletoId.set(null);
      }
    });
  }

  // --- Display Formatters ---
  formatJid(jid: string): string {
    if (!jid) return '';
    return jid.split('@')[0];
  }

  getDisplayName(chat: any): string {
    // Clientes PHN_ -> nome do cadastro (mais polido); contatos pessoais -> nome salvo na agenda
    if (chat.cliente_nome) return chat.cliente_nome;
    if (chat.cliente && chat.cliente.nome) return chat.cliente.nome;
    return chat.nome_salvo || this.formatJid(chat.remote_jid) || 'Desconhecido';
  }

  getTipoContatoDisplay(tipo: string): string {
    const tipos: { [key: string]: string } = {
      cliente: 'Cliente',
      pessoal: 'Pessoal',
      desconhecido: 'Desconhecido'
    };
    return tipos[tipo] || 'Desconhecido';
  }

  getTipoContatoBadgeClass(tipo: string): string {
    const classes: { [key: string]: string } = {
      cliente: 'badge-success',
      pessoal: 'badge-info',
      desconhecido: 'badge-warning'
    };
    return classes[tipo] || 'badge-warning';
  }

  formatTime(dateStr: string): string {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }

  getStateDisplay(state: string): string {
    const states: { [key: string]: string } = {
      nova: 'Nova',
      aguardando_verificacao: 'Verificação Pendente',
      verificada: 'Verificada',
      intencao_capturada: 'Intenção Capturada',
      aguardando_boleto: 'Aguardando Boleto',
      boleto_enviado: 'Boleto Enviado',
      encerrada: 'Encerrada'
    };
    return states[state] || state;
  }

  getStateBadgeClass(state: string): string {
    const classes: { [key: string]: string } = {
      nova: 'badge-info',
      aguardando_verificacao: 'badge-warning',
      verificada: 'badge-success',
      intencao_capturada: 'badge-info',
      aguardando_boleto: 'badge-warning',
      boleto_enviado: 'badge-success',
      encerrada: 'badge-danger'
    };
    return classes[state] || 'badge-info';
  }

  getSolTipoDisplay(tipo: string): string {
    const tipos: { [key: string]: string } = {
      quitar: 'Quitar Contrato',
      amortizar: 'Amortizar',
      renovar: 'Renovar',
      parcela: 'Parcela',
      segunda_via: '2ª Via de Boleto',
      duvida: 'Dúvida Geral'
    };
    return tipos[tipo] || tipo;
  }

  getSolStatusDisplay(status: string): string {
    const statuses: { [key: string]: string } = {
      pendente: 'Pendente Operador',
      boleto_enviado: 'Boleto Enviado',
      concluida: 'Concluída'
    };
    return statuses[status] || status;
  }

  getSolStatusBadgeClass(status: string): string {
    const classes: { [key: string]: string } = {
      pendente: 'badge-warning',
      boleto_enviado: 'badge-info',
      concluida: 'badge-success'
    };
    return classes[status] || 'badge-info';
  }
}
