import { Component, inject, signal, computed, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePipe } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { IconComponent } from '../../shared/icon/icon.component';

interface FormResposta {
  id?: number;
  texto: string;
  arquivo: any;
  arquivo_url?: string | null;
  fileObject?: File | null;
}

@Component({
  selector: 'app-faq',
  standalone: true,
  imports: [FormsModule, DatePipe, IconComponent],
  template: `
    <div class="faq-wrapper">
      <div class="faq-header flex align-center justify-between">
        <div>
          <h1>FAQs & Respostas da IA</h1>
          <p class="text-muted">Cadastre perguntas frequentes e as mensagens sequenciais de resposta.</p>
        </div>
        @if (activeTab() === 'faqs') {
          <button class="btn btn-primary" (click)="openCreateModal()">
            + Nova FAQ
          </button>
        }
      </div>

      <!-- Tab Navigation -->
      <div class="tabs flex gap-2">
        <button class="tab-btn" [class.active]="activeTab() === 'faqs'" (click)="activeTab.set('faqs')">
          FAQs
        </button>
        <button class="tab-btn" [class.active]="activeTab() === 'sugestoes'" (click)="activeTab.set('sugestoes')">
          Sugestões ({{ sugeridas().length }})
        </button>
      </div>

      <!-- FAQ Table -->
      @if (activeTab() === 'faqs') {
        @if (loading() && faqs().length === 0) {
          <div class="loading-container">
            <div class="spinner"></div>
            <p>Carregando FAQs...</p>
          </div>
        } @else {
          <div class="table-container margin-top">
            <table>
              <thead>
                <tr>
                  <th>Pergunta</th>
                  <th>Qtd. Respostas</th>
                  <th>Status</th>
                  <th style="width: 160px; text-align: right;">Ações</th>
                </tr>
              </thead>
              <tbody>
                @for (faq of faqs(); track faq.id) {
                  <tr>
                    <td data-label="Pergunta"><strong>{{ faq.pergunta }}</strong></td>
                    <td data-label="Respostas">{{ faq.respostas?.length || 0 }} mensagens</td>
                    <td data-label="Status">
                      <button
                        class="badge-toggle"
                        [class.active]="faq.ativo"
                        (click)="toggleFAQ(faq.id)"
                      >
                        {{ faq.ativo ? 'Ativo' : 'Inativo' }}
                      </button>
                    </td>
                    <td data-label="Ações" style="text-align: right;">
                      <div class="flex gap-2 justify-end">
                        <button class="btn btn-secondary btn-xs" (click)="openEditModal(faq)">Editar</button>
                        <button class="btn btn-danger btn-xs" (click)="confirmDeleteFAQ(faq)">Excluir</button>
                      </div>
                    </td>
                  </tr>
                } @empty {
                  <tr>
                    <td colspan="4" class="text-muted text-center" style="padding: 32px;">
                      Nenhuma FAQ cadastrada. Clique em "+ Nova FAQ" para começar.
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      }

      <!-- Sugestões Pendentes (fallback do bot, curadoria humana) -->
      @if (activeTab() === 'sugestoes') {
        @if (loadingSugeridas() && sugeridas().length === 0) {
          <div class="loading-container">
            <div class="spinner"></div>
            <p>Carregando sugestões...</p>
          </div>
        } @else {
          <div class="table-container margin-top">
            <table>
              <thead>
                <tr>
                  <th>Pergunta sugerida</th>
                  <th style="width: 110px;">Ocorrências</th>
                  <th style="width: 140px;">Data</th>
                  <th style="width: 260px; text-align: right;">Ações</th>
                </tr>
              </thead>
              <tbody>
                @for (s of sugeridas(); track s.id) {
                  <tr>
                    <td data-label="Pergunta sugerida" [title]="s.pergunta_original || ''">
                      @if (editingSugeridaId() === s.id) {
                        <input type="text" [(ngModel)]="editPerguntaTexto" class="inline-edit-input" />
                        <div class="flex gap-2 margin-top-xs">
                          <button class="btn btn-primary btn-xs" (click)="saveEditPergunta(s)">Salvar</button>
                          <button class="btn btn-secondary btn-xs" (click)="cancelEditPergunta()">Cancelar</button>
                        </div>
                      } @else {
                        <strong>{{ s.pergunta }}</strong>
                        @if (s.pergunta_original && s.pergunta_original !== s.pergunta) {
                          <div class="text-muted text-small margin-top-xs">"{{ s.pergunta_original }}"</div>
                        }
                      }
                    </td>
                    <td data-label="Ocorrências"><span class="badge badge-info">{{ s.ocorrencias }}x</span></td>
                    <td data-label="Data" class="text-muted text-small">{{ s.criado_em | date:'dd/MM/yyyy' }}</td>
                    <td data-label="Ações" style="text-align: right;">
                      <div class="flex gap-2 justify-end">
                        <button class="btn btn-secondary btn-xs" (click)="startEditPergunta(s)">Editar</button>
                        <button class="btn btn-primary btn-xs" (click)="openAprovarModal(s)">Aprovar</button>
                        <button class="btn btn-danger btn-xs" (click)="confirmRejeitar(s)">Rejeitar</button>
                      </div>
                    </td>
                  </tr>
                } @empty {
                  <tr>
                    <td colspan="4" class="text-muted text-center" style="padding: 32px;">
                      Nenhuma sugestão pendente de revisão no momento.
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      }

      <!-- Create / Edit Modal -->
      @if (showFormModal()) {
        <div class="modal-overlay">
          <div class="modal-content modal-large fade-in">
            <h2>{{ formTitle() }}</h2>
            <form (ngSubmit)="saveFAQ()">
              <div class="form-group margin-bottom-sm">
                <label for="pergunta">Pergunta / Gatilho</label>
                <input 
                  type="text" 
                  id="pergunta" 
                  name="pergunta" 
                  [(ngModel)]="formPergunta" 
                  required 
                  placeholder="Ex: Como faço para renovar meu contrato?"
                />
              </div>

              <div class="form-group margin-bottom">
                <label class="checkbox-container">
                  <input type="checkbox" name="ativo" [(ngModel)]="formAtivo" />
                  <span class="custom-checkbox"></span>
                  <span>FAQ Ativa para respostas automáticas</span>
                </label>
              </div>

              <!-- Nested Respostas list -->
              <div class="nested-respostas-section">
                <div class="flex justify-between align-center margin-bottom-sm">
                  <h3>Mensagens de Resposta (Sequência)</h3>
                  <button type="button" class="btn btn-secondary btn-small" (click)="addRespostaRow()">
                    + Adicionar Mensagem
                  </button>
                </div>

                <div class="respostas-list">
                  @for (r of formRespostas(); track idx; let idx = $index) {
                    <div class="resposta-row card">
                      <div class="resposta-row-header flex justify-between align-center">
                        <span class="badge badge-info">Mensagem {{ idx + 1 }}</span>
                        <div class="flex gap-2">
                          <button 
                            type="button" 
                            class="icon-btn" 
                            [disabled]="idx === 0" 
                            (click)="moveResposta(idx, 'up')"
                            title="Subir"
                          >
                            <app-icon name="chevron-up" [size]="14"></app-icon>
                          </button>
                          <button
                            type="button"
                            class="icon-btn"
                            [disabled]="idx === formRespostas().length - 1"
                            (click)="moveResposta(idx, 'down')"
                            title="Descer"
                          >
                            <app-icon name="chevron-down" [size]="14"></app-icon>
                          </button>
                          <button
                            type="button"
                            class="icon-btn text-danger"
                            (click)="removeRespostaRow(idx)"
                            title="Remover"
                          >
                            <app-icon name="trash" [size]="14"></app-icon>
                          </button>
                        </div>
                      </div>

                      <div class="form-group margin-top-sm">
                        <textarea 
                          [name]="'resp_' + idx" 
                          [(ngModel)]="r.texto" 
                          placeholder="Digite a mensagem de texto..."
                          rows="2"
                        ></textarea>
                      </div>

                      <!-- Hidden File Input for PDF/Image -->
                      <div class="file-uploader-group flex align-center gap-2 margin-top-sm">
                        <button 
                          type="button" 
                          class="btn btn-secondary btn-small" 
                          (click)="fileInput.click()"
                        >
                          <app-icon name="paperclip" [size]="14"></app-icon> Anexar PDF / Imagem
                        </button>
                        <input 
                          #fileInput
                          type="file" 
                          style="display: none;" 
                          (change)="onFileSelected($event, idx)" 
                        />
                        
                        @if (r.fileObject) {
                          <span class="file-badge success">
                            Novo: {{ r.fileObject.name }}
                            <button type="button" class="clear-file" (click)="clearFile(idx)">×</button>
                          </span>
                        } @else if (r.arquivo) {
                          <span class="file-badge">
                            Anexo: {{ getFileName(r.arquivo) }}
                            <button type="button" class="clear-file" (click)="clearFile(idx)">×</button>
                          </span>
                        }
                      </div>
                    </div>
                  } @empty {
                    <p class="text-muted text-center" style="padding: 16px;">
                      Nenhuma mensagem cadastrada. A IA enviará um retorno vazio se acionada. Adicione ao menos uma resposta.
                    </p>
                  }
                </div>
              </div>

              <div class="form-actions flex justify-end gap-2 margin-top">
                <button type="button" class="btn btn-secondary" (click)="showFormModal.set(false)">Cancelar</button>
                <button type="submit" class="btn btn-primary" [disabled]="saving() || !formPergunta.trim()">
                  {{ saving() ? 'Salvando...' : 'Salvar FAQ' }}
                </button>
              </div>
            </form>
          </div>
        </div>
      }

      <!-- Delete Confirmation Modal -->
      @if (showDeleteModal()) {
        <div class="modal-overlay">
          <div class="modal-content fade-in">
            <h2>Confirmar Exclusão</h2>
            <p>Tem certeza que deseja excluir permanentemente a FAQ <strong>"{{ faqToDelete()?.pergunta }}"</strong>?</p>
            <p class="text-muted text-small margin-top-sm">Esta ação não pode ser desfeita e removerá todas as respostas vinculadas.</p>
            
            <div class="form-actions flex justify-end gap-2 margin-top">
              <button type="button" class="btn btn-secondary" (click)="showDeleteModal.set(false)">Cancelar</button>
              <button type="button" class="btn btn-danger" (click)="deleteFAQ()">Confirmar Exclusão</button>
            </div>
          </div>
        </div>
      }

      <!-- Aprovar Sugestão Modal -->
      @if (showAprovarModal()) {
        <div class="modal-overlay">
          <div class="modal-content modal-large fade-in">
            <h2>Aprovar Sugestão de FAQ</h2>
            <p class="text-muted margin-bottom-sm">Revise a pergunta e cadastre as mensagens de resposta antes de publicar como FAQ ativa.</p>

            <div class="form-group margin-bottom-sm">
              <label for="aprovarPergunta">Pergunta Final</label>
              <input
                type="text"
                id="aprovarPergunta"
                name="aprovarPergunta"
                [(ngModel)]="aprovarPergunta"
                required
              />
            </div>

            <div class="nested-respostas-section">
              <div class="flex justify-between align-center margin-bottom-sm">
                <h3>Mensagens de Resposta (Sequência)</h3>
                <button type="button" class="btn btn-secondary btn-small" (click)="addAprovarRespostaRow()">
                  + Adicionar Mensagem
                </button>
              </div>

              <div class="respostas-list">
                @for (r of aprovarRespostas(); track idx; let idx = $index) {
                  <div class="resposta-row card">
                    <div class="resposta-row-header flex justify-between align-center">
                      <span class="badge badge-info">Mensagem {{ idx + 1 }}</span>
                      <button
                        type="button"
                        class="icon-btn text-danger"
                        (click)="removeAprovarRespostaRow(idx)"
                        title="Remover"
                      >
                        <app-icon name="trash" [size]="14"></app-icon>
                      </button>
                    </div>
                    <div class="form-group margin-top-sm">
                      <textarea
                        [name]="'aprovar_resp_' + idx"
                        [(ngModel)]="r.texto"
                        placeholder="Digite a mensagem de texto..."
                        rows="2"
                      ></textarea>
                    </div>
                  </div>
                } @empty {
                  <p class="text-muted text-center" style="padding: 16px;">
                    Nenhuma mensagem cadastrada. Adicione ao menos uma resposta.
                  </p>
                }
              </div>
            </div>

            <div class="form-actions flex justify-end gap-2 margin-top">
              <button type="button" class="btn btn-secondary" (click)="showAprovarModal.set(false)">Cancelar</button>
              <button
                type="button"
                class="btn btn-primary"
                [disabled]="aprovando() || !aprovarPergunta.trim()"
                (click)="confirmarAprovacao()"
              >
                {{ aprovando() ? 'Aprovando...' : 'Aprovar & Publicar FAQ' }}
              </button>
            </div>
          </div>
        </div>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.Eager,
  styles: [`
    .faq-wrapper {
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .faq-header h1 {
      font-size: 26px;
      font-weight: 700;
    }
    .margin-top {
      margin-top: 16px;
    }
    .margin-bottom {
      margin-bottom: 20px;
    }
    .margin-bottom-sm {
      margin-bottom: 12px;
    }
    .margin-top-sm {
      margin-top: 8px;
    }
    .badge-toggle {
      border: none;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 600;
      border-radius: 9999px;
      cursor: pointer;
      text-transform: uppercase;
      transition: all var(--transition-fast);
      background-color: var(--color-danger-bg);
      color: var(--color-danger);
    }
    .badge-toggle.active {
      background-color: var(--color-success-bg);
      color: var(--color-success);
    }
    .modal-large {
      max-width: 700px;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
    }
    .modal-large form {
      overflow-y: auto;
      flex: 1;
      padding-right: 4px;
    }
    .nested-respostas-section {
      background-color: var(--bg-primary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 18px;
      margin-top: 18px;
    }
    .respostas-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-height: 350px;
      overflow-y: auto;
      padding: 4px;
    }
    .resposta-row {
      background-color: var(--bg-secondary);
      border-color: var(--border-color);
      padding: 14px;
    }
    .resposta-row textarea {
      width: 100%;
      max-width: 100%;
      resize: vertical;
    }
    .file-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      background-color: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      padding: 4px 8px;
      color: var(--text-secondary);
    }
    .file-badge.success {
      background-color: var(--color-success-bg);
      color: var(--color-success);
      border-color: rgba(16, 185, 129, 0.2);
    }
    .clear-file {
      background: transparent;
      border: none;
      color: var(--color-danger);
      font-weight: bold;
      cursor: pointer;
      font-size: 14px;
      line-height: 1;
    }
    .btn-xs {
      padding: 4px 8px;
      font-size: 12px;
    }
    .loading-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 64px 0;
      gap: 16px;
    }
    .fade-in {
      animation: fadeIn 0.2s ease-out;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .tabs {
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 1px;
    }
    .tab-btn {
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text-secondary);
      font-weight: 600;
      padding: 10px 16px;
      border-radius: 0;
      cursor: pointer;
      transition: all var(--transition-fast);
    }
    .tab-btn:hover {
      color: var(--text-primary);
      border-bottom-color: var(--border-color);
    }
    .tab-btn.active {
      color: var(--color-accent);
      border-bottom-color: var(--color-accent);
    }
    .inline-edit-input {
      width: 100%;
      padding: 6px 8px;
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      background-color: var(--bg-primary);
      color: var(--text-primary);
      font-size: 13px;
    }
    .text-center { text-align: center; }

    /* Mobile (< 640px): abas com wrap, tabelas viram cards empilhados,
       modais e editor de FAQ com largura fluida. */
    @media (max-width: 639px) {
      .faq-header {
        flex-wrap: wrap;
        gap: 12px;
      }
      .tabs {
        flex-wrap: wrap;
      }
      .table-container table,
      .table-container thead,
      .table-container tbody,
      .table-container tr,
      .table-container td {
        display: block;
        width: 100%;
      }
      .table-container thead {
        display: none;
      }
      .table-container tr {
        border-bottom: 1px solid var(--border-color);
        padding: 10px 4px;
      }
      .table-container tr:last-child {
        border-bottom: none;
      }
      .table-container td {
        padding: 6px 4px;
        text-align: left !important;
      }
      .table-container td::before {
        content: attr(data-label);
        display: block;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.02em;
        color: var(--text-secondary);
        font-weight: 600;
        margin-bottom: 4px;
      }
      .table-container td .flex.gap-2 {
        flex-wrap: wrap;
      }
      .modal-large {
        max-height: 92vh;
      }
      .respostas-list {
        max-height: 42vh;
      }
      .file-uploader-group {
        flex-wrap: wrap;
      }
      .file-badge {
        max-width: 100%;
        word-break: break-word;
      }
    }
  `]
})
export class FAQComponent implements OnInit {
  private apiService = inject(ApiService);

  faqs = signal<any[]>([]);
  loading = signal(false);
  saving = signal(false);

  activeTab = signal<'faqs' | 'sugestoes'>('faqs');

  // Modal Controls
  showFormModal = signal(false);
  showDeleteModal = signal(false);
  formTitle = signal('Nova FAQ');

  // Form State
  formFaqId: number | null = null;
  formPergunta = '';
  formAtivo = true;
  formRespostas = signal<FormResposta[]>([]);

  // Delete State
  faqToDelete = signal<any | null>(null);

  // Sugestões pendentes (curadoria do fallback do bot)
  sugeridas = signal<any[]>([]);
  loadingSugeridas = signal(false);

  editingSugeridaId = signal<number | null>(null);
  editPerguntaTexto = '';

  showAprovarModal = signal(false);
  aprovando = signal(false);
  aprovarSugestaoId: number | null = null;
  aprovarPergunta = '';
  aprovarRespostas = signal<{ texto: string }[]>([]);

  ngOnInit(): void {
    this.loadFAQs();
    this.loadSugeridas();
  }

  loadFAQs(): void {
    this.loading.set(true);
    this.apiService.getFAQs().subscribe({
      next: (data) => {
        this.faqs.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      }
    });
  }

  toggleFAQ(id: number): void {
    // Optimistic UI update
    this.faqs.update(list => list.map(item => {
      if (item.id === id) {
        return { ...item, ativo: !item.ativo };
      }
      return item;
    }));

    this.apiService.toggleFAQ(id).subscribe({
      error: () => {
        // Revert on error
        this.loadFAQs();
      }
    });
  }

  openCreateModal(): void {
    this.formTitle.set('Nova FAQ');
    this.formFaqId = null;
    this.formPergunta = '';
    this.formAtivo = true;
    this.formRespostas.set([
      { texto: '', arquivo: null }
    ]);
    this.showFormModal.set(true);
  }

  openEditModal(faq: any): void {
    this.formTitle.set('Editar FAQ');
    this.formFaqId = faq.id;
    this.formPergunta = faq.pergunta;
    this.formAtivo = faq.ativo;
    
    // Copy existing answers to form signals
    const mapped = (faq.respostas || []).map((r: any) => ({
      id: r.id,
      texto: r.texto,
      arquivo: r.arquivo,
      arquivo_url: r.arquivo_url
    }));
    this.formRespostas.set(mapped);
    
    this.showFormModal.set(true);
  }

  addRespostaRow(): void {
    this.formRespostas.update(list => [...list, { texto: '', arquivo: null }]);
  }

  removeRespostaRow(index: number): void {
    this.formRespostas.update(list => list.filter((_, idx) => idx !== index));
  }

  moveResposta(index: number, direction: 'up' | 'down'): void {
    const list = [...this.formRespostas()];
    if (direction === 'up' && index > 0) {
      const temp = list[index];
      list[index] = list[index - 1];
      list[index - 1] = temp;
    } else if (direction === 'down' && index < list.length - 1) {
      const temp = list[index];
      list[index] = list[index + 1];
      list[index + 1] = temp;
    }
    this.formRespostas.set(list);
  }

  onFileSelected(event: any, index: number): void {
    const file = event.target.files[0];
    if (file) {
      this.formRespostas.update(list => list.map((item, idx) => {
        if (idx === index) {
          return { ...item, fileObject: file };
        }
        return item;
      }));
    }
  }

  clearFile(index: number): void {
    this.formRespostas.update(list => list.map((item, idx) => {
      if (idx === index) {
        return { ...item, arquivo: null, fileObject: null, arquivo_url: null };
      }
      return item;
    }));
  }

  saveFAQ(): void {
    this.saving.set(true);
    
    const rawRespostas = this.formRespostas().map((r, i) => ({
      id: r.id,
      ordem: i,
      texto: r.texto,
      arquivo: r.arquivo // Keep reference to old file path if not cleared
    }));

    const faqPayload = {
      pergunta: this.formPergunta,
      ativo: this.formAtivo,
      respostas: rawRespostas
    };

    const formData = new FormData();
    formData.append('faq', JSON.stringify(faqPayload));

    // Append file objects dynamically
    this.formRespostas().forEach((r, i) => {
      if (r.fileObject) {
        formData.append(`arquivo_${i}`, r.fileObject);
      }
    });

    const request = this.formFaqId 
      ? this.apiService.updateFAQ(this.formFaqId, formData)
      : this.apiService.createFAQ(formData);

    request.subscribe({
      next: () => {
        this.showFormModal.set(false);
        this.loadFAQs();
        this.saving.set(false);
      },
      error: () => {
        this.saving.set(false);
      }
    });
  }

  confirmDeleteFAQ(faq: any): void {
    this.faqToDelete.set(faq);
    this.showDeleteModal.set(true);
  }

  deleteFAQ(): void {
    const faq = this.faqToDelete();
    if (!faq) return;

    this.apiService.deleteFAQ(faq.id).subscribe({
      next: () => {
        this.showDeleteModal.set(false);
        this.loadFAQs();
      }
    });
  }

  getFileName(url: string): string {
    if (!url) return '';
    return url.split('/').pop() || 'Arquivo';
  }

  // --- Sugestões de FAQ (curadoria do fallback do bot) ---
  loadSugeridas(): void {
    this.loadingSugeridas.set(true);
    this.apiService.getFaqsSugeridas('pendente').subscribe({
      next: (data) => {
        this.sugeridas.set(data);
        this.loadingSugeridas.set(false);
      },
      error: () => this.loadingSugeridas.set(false)
    });
  }

  startEditPergunta(s: any): void {
    this.editingSugeridaId.set(s.id);
    this.editPerguntaTexto = s.pergunta;
  }

  cancelEditPergunta(): void {
    this.editingSugeridaId.set(null);
    this.editPerguntaTexto = '';
  }

  saveEditPergunta(s: any): void {
    const texto = this.editPerguntaTexto.trim();
    if (!texto) return;
    this.apiService.updateFaqSugerida(s.id, { pergunta: texto }).subscribe({
      next: (updated) => {
        this.sugeridas.update(list => list.map(item => item.id === s.id ? updated : item));
        this.cancelEditPergunta();
      }
    });
  }

  confirmRejeitar(s: any): void {
    if (!confirm(`Rejeitar a sugestão "${s.pergunta}"? Esta ação não pode ser desfeita.`)) return;
    this.apiService.rejeitarFaqSugerida(s.id).subscribe({
      next: () => {
        this.sugeridas.update(list => list.filter(item => item.id !== s.id));
      }
    });
  }

  openAprovarModal(s: any): void {
    this.aprovarSugestaoId = s.id;
    this.aprovarPergunta = s.pergunta;
    this.aprovarRespostas.set([{ texto: '' }]);
    this.showAprovarModal.set(true);
  }

  addAprovarRespostaRow(): void {
    this.aprovarRespostas.update(list => [...list, { texto: '' }]);
  }

  removeAprovarRespostaRow(index: number): void {
    this.aprovarRespostas.update(list => list.filter((_, idx) => idx !== index));
  }

  confirmarAprovacao(): void {
    const sugestaoId = this.aprovarSugestaoId;
    if (!sugestaoId || !this.aprovarPergunta.trim()) return;

    this.aprovando.set(true);
    const respostas = this.aprovarRespostas()
      .map((r, i) => ({ ordem: i, texto: r.texto }))
      .filter(r => r.texto.trim());

    this.apiService.aprovarFaqSugerida(sugestaoId, {
      pergunta_final: this.aprovarPergunta.trim(),
      respostas
    }).subscribe({
      next: () => {
        this.aprovando.set(false);
        this.showAprovarModal.set(false);
        this.sugeridas.update(list => list.filter(item => item.id !== sugestaoId));
        this.loadFAQs();
      },
      error: () => {
        this.aprovando.set(false);
      }
    });
  }
}
