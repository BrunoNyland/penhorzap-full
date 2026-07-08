import { Component, inject, signal, computed, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
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
  imports: [FormsModule, IconComponent],
  template: `
    <div class="faq-wrapper">
      <div class="faq-header flex align-center justify-between">
        <div>
          <h1>FAQs & Respostas da IA</h1>
          <p class="text-muted">Cadastre perguntas frequentes e as mensagens sequenciais de resposta.</p>
        </div>
        <button class="btn btn-primary" (click)="openCreateModal()">
          + Nova FAQ
        </button>
      </div>

      <!-- FAQ Table -->
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
                  <td><strong>{{ faq.pergunta }}</strong></td>
                  <td>{{ faq.respostas?.length || 0 }} mensagens</td>
                  <td>
                    <button 
                      class="badge-toggle"
                      [class.active]="faq.ativo"
                      (click)="toggleFAQ(faq.id)"
                    >
                      {{ faq.ativo ? 'Ativo' : 'Inativo' }}
                    </button>
                  </td>
                  <td style="text-align: right;">
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
    </div>
  `,
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
  `]
})
export class FAQComponent implements OnInit {
  private apiService = inject(ApiService);

  faqs = signal<any[]>([]);
  loading = signal(false);
  saving = signal(false);

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

  ngOnInit(): void {
    this.loadFAQs();
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
}
