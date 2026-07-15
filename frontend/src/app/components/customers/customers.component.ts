import { Component, inject, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePipe, CurrencyPipe, NgClass } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { IconComponent } from '../../shared/icon/icon.component';

@Component({
  selector: 'app-customers',
  standalone: true,
  imports: [FormsModule, DatePipe, CurrencyPipe, NgClass, IconComponent],
  template: `
    <div class="customers-wrapper">
      <div class="customers-header">
        <h1>Clientes cadastrados</h1>
        <p class="text-muted">Consulte dados cadastrais, contratos ativos e configure o bloqueio individual do robô.</p>
      </div>

      <!-- Filters -->
      <div class="card flex align-center gap-4 wrap">
        <div class="form-group flex-1">
          <input 
            type="text" 
            placeholder="Buscar por Nome ou CPF..." 
            [(ngModel)]="searchQuery" 
            (ngModelChange)="loadClientes()"
          />
        </div>
        <div class="form-group filter-select-group">
          <select [(ngModel)]="filterBloqueado" (change)="loadClientes()">
            <option value="">Todos os Clientes</option>
            <option value="1">Apenas Bloqueados IA</option>
          </select>
        </div>
      </div>

      <!-- Customer Grid -->
      @if (loading() && Clientes().length === 0) {
        <div class="loading-container">
          <div class="spinner"></div>
          <p>Carregando registros de clientes...</p>
        </div>
      } @else {
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>CPF</th>
                <th>Nome</th>
                <th>Contratos Ativos</th>
                <th>Total Empréstimo</th>
                <th>Total Avaliação</th>
                <th>Limite Especial</th>
                <th>Status Bot</th>
                <th style="text-align: right;">Ações</th>
              </tr>
            </thead>
            <tbody>
              @for (c of Clientes(); track c.cpf) {
                <tr>
                  <td><code>{{ c.cpf }}</code></td>
                  <td><strong>{{ c.nome }}</strong></td>
                  <td>{{ c.num_contratos_ativos }}</td>
                  <td>{{ c.total_emprestimo_ativo | currency:'BRL':'symbol':'1.2-2':'pt-BR' }}</td>
                  <td>{{ c.total_avaliacao_ativo | currency:'BRL':'symbol':'1.2-2':'pt-BR' }}</td>
                  <td>{{ c.limite_especial | currency:'BRL':'symbol':'1.2-2':'pt-BR' }}</td>
                  <td>
                    <span class="badge" [ngClass]="c.bloqueado_ia ? 'badge-danger' : 'badge-success'">
                      {{ c.bloqueado_ia ? 'Bloqueado' : 'Ativo' }}
                    </span>
                  </td>
                  <td style="text-align: right;">
                    <button class="btn btn-secondary btn-xs" (click)="openDetail(c.cpf)">
                      Visualizar Contratos
                    </button>
                  </td>
                </tr>
              } @empty {
                <tr>
                  <td colspan="8" class="text-center text-muted" style="padding: 32px;">
                    Nenhum cliente localizado com os filtros selecionados.
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }

      <!-- Details Modal (with Contracts and Block Forms) -->
      @if (showDetailModal() && selectedCliente()) {
        <div class="modal-overlay">
          <div class="modal-content modal-large fade-in">
            <div class="modal-header flex justify-between align-center border-bottom padding-bottom-sm">
              <div>
                <h2>{{ selectedCliente().nome }}</h2>
                <p class="text-muted">CPF: {{ selectedCliente().cpf }}</p>
              </div>
              <button type="button" class="clear-file" style="font-size: 24px;" (click)="showDetailModal.set(false)">×</button>
            </div>

            <div class="modal-body-scroll margin-top">
              <div class="grid-2">
                <!-- Cadastro info -->
                <div>
                  <h4>Dados Cadastrais</h4>
                  <ul class="detail-list margin-top-xs">
                    <li>Logradouro: <strong>{{ selectedCliente().logradouro || '-' }}</strong></li>
                    <li>Bairro: <strong>{{ selectedCliente().bairro || '-' }}</strong></li>
                    <li>Cidade/UF: <strong>{{ selectedCliente().cidade || '-' }}</strong></li>
                    <li>CEP: <strong>{{ selectedCliente().cep || '-' }}</strong></li>
                    <li>Nascimento: <strong>{{ selectedCliente().aniversario | date:'dd/MM/yyyy' }}</strong></li>
                    <li>Status CPF: <strong>{{ selectedCliente().situacao_cpf || '-' }}</strong></li>
                  </ul>
                  
                  <h4 class="margin-top">Telefones Vinculados</h4>
                  <ul class="detail-list margin-top-xs">
                    @for (t of selectedCliente().telefones; track t.numero) {
                      <li><app-icon name="phone" [size]="14"></app-icon> <code>{{ t.numero }}</code> <span class="text-muted">({{ t.numero_bruto }})</span></li>
                    } @empty {
                      <li class="text-muted">Nenhum telefone normalizado.</li>
                    }
                  </ul>
                </div>

                <!-- AI Blocking controller -->
                <div class="card block-card">
                  <h4>Status do Assistente IA</h4>
                  <div class="margin-top-xs">
                    @if (selectedCliente().bloqueado_ia) {
                      <div class="badge badge-danger margin-bottom-sm">IA Bloqueada para responder este cliente</div>
                      <p class="text-small text-muted">
                        Bloqueado em: <strong>{{ selectedCliente().bloqueado_em | date:'dd/MM/yyyy HH:mm' }}</strong>
                      </p>
                      @if (selectedCliente().bloqueado_motivo) {
                        <p class="text-small margin-top-xs">
                          Motivo: <em class="text-secondary">"{{ selectedCliente().bloqueado_motivo }}"</em>
                        </p>
                      }
                      <button 
                        class="btn btn-primary btn-small margin-top" 
                        (click)="toggleBloqueio('desbloquear')"
                      >
                        <app-icon name="check" [size]="14"></app-icon> Desbloquear Respostas da IA
                      </button>
                    } @else {
                      <div class="badge badge-success margin-bottom-sm">IA liberada para responder automaticamente</div>
                      <p class="text-small text-muted">Se você marcar o cliente como bloqueado, o bot registrará as mensagens mas nunca responderá.</p>
                      
                      <div class="form-group margin-top-sm">
                        <label for="motivo_bloqueio">Motivo do Bloqueio</label>
                        <input 
                          type="text" 
                          id="motivo_bloqueio" 
                          placeholder="Ex: Cliente quer falar apenas com gerente..." 
                          [(ngModel)]="blockMotivo"
                        />
                      </div>
                      
                      <button 
                        class="btn btn-danger btn-small margin-top-sm" 
                        [disabled]="!blockMotivo.trim()"
                        (click)="toggleBloqueio('bloquear')"
                      >
                        <app-icon name="flag" [size]="14"></app-icon> Bloquear Respostas da IA
                      </button>
                    }
                  </div>
                </div>
              </div>

              <!-- Pawn contracts -->
              <div class="contracts-section margin-top">
                <h4>Contratos de Penhor Ativos (ERP)</h4>
                <div class="table-container margin-top-xs">
                  <table>
                    <thead>
                      <tr>
                        <th>Nº Contrato</th>
                        <th>Garantia / Descrição</th>
                        <th>Peso (g)</th>
                        <th>Atraso</th>
                        <th>Vencimento</th>
                        <th>Empréstimo</th>
                        <th>Avaliação</th>
                        <th>Vlr. Parcela</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (con of selectedCliente().contratos_penhor; track con.contrato) {
                        <tr>
                          <td><code>{{ con.contrato }}</code></td>
                          <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" [title]="con.laudo || '-'">
                            {{ con.laudo || '-' }}
                          </td>
                          <td>{{ con.peso ? con.peso + 'g' : '-' }}</td>
                          <td>
                            @if (con.atraso > 0) {
                              <span class="text-danger" style="font-weight: bold;">{{ con.atraso }} dias</span>
                            } @else {
                              <span class="text-success">Em dia</span>
                            }
                          </td>
                          <td>{{ con.data_vencimento | date:'dd/MM/yyyy' }}</td>
                          <td>{{ con.vlr_emprestimo | currency:'BRL':'symbol':'1.2-2':'pt-BR' }}</td>
                          <td>{{ con.vlr_avaliacao | currency:'BRL':'symbol':'1.2-2':'pt-BR' }}</td>
                          <td>{{ con.vlr_parcela_atualizada | currency:'BRL':'symbol':'1.2-2':'pt-BR' }}</td>
                          <td>
                            <span class="badge" [ngClass]="getContratoBadgeClass(con.situacao_codigo)">
                              {{ con.situacao }} ({{ con.situacao_codigo }})
                            </span>
                          </td>
                        </tr>
                      } @empty {
                        <tr>
                          <td colspan="9" class="text-center text-muted" style="padding: 16px;">
                            Nenhum contrato ativo localizado para este CPF no ERP.
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      }
    </div>
  `,
  styles: [`
    .customers-wrapper {
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .customers-header h1 {
      font-size: 26px;
      font-weight: 700;
    }
    .wrap { flex-wrap: wrap; }
    .filter-select-group {
      width: 200px;
      max-width: 100%;
    }
    .btn-xs {
      padding: 4px 8px;
      font-size: 12px;
    }
    .margin-top { margin-top: 18px; }
    .margin-top-xs { margin-top: 6px; }
    .margin-top-sm { margin-top: 10px; }
    .margin-bottom-sm { margin-bottom: 10px; }
    .border-bottom {
      border-bottom: 1px solid var(--border-color);
    }
    .padding-bottom-sm {
      padding-bottom: 12px;
    }
    .modal-large {
      max-width: 800px;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
    }
    .modal-body-scroll {
      overflow-y: auto;
      flex: 1;
      padding-right: 4px;
    }
    .detail-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 13px;
    }
    .block-card {
      background-color: var(--bg-surface);
      border-color: var(--border-color);
      padding: 16px;
    }
    .contracts-section {
      border-top: 1px solid var(--border-color);
      padding-top: 18px;
    }
    .text-small { font-size: 12px; }
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

    @media (max-width: 639px) {
      .filter-select-group {
        width: 100%;
      }
      .grid-2 {
        display: grid;
        grid-template-columns: 1fr;
        gap: 20px;
      }
      .modal-large {
        max-width: 100%;
        max-height: 100vh;
        border-radius: 0;
      }
    }
  `]
})
export class CustomersComponent implements OnInit {
  private apiService = inject(ApiService);

  Clientes = signal<any[]>([]);
  loading = signal(false);

  // Search/Filters
  searchQuery = '';
  filterBloqueado = '';

  // Detail Modal State
  showDetailModal = signal(false);
  selectedCliente = signal<any | null>(null);
  blockMotivo = '';

  ngOnInit(): void {
    this.loadClientes();
  }

  loadClientes(): void {
    this.loading.set(true);
    this.apiService.getClientes({
      q: this.searchQuery,
      bloqueado: this.filterBloqueado,
      ativos_somente: '1'
    }).subscribe({
      next: (data) => {
        this.Clientes.set(data);
        this.loading.set(false);
      },
      error: () => this.loading.set(false)
    });
  }

  openDetail(cpf: string): void {
    this.apiService.getCliente(cpf).subscribe({
      next: (res) => {
        this.selectedCliente.set(res);
        this.blockMotivo = '';
        this.showDetailModal.set(true);
      }
    });
  }

  toggleBloqueio(acao: 'bloquear' | 'desbloquear'): void {
    const customer = this.selectedCliente();
    if (!customer) return;

    this.apiService.toggleClienteBloqueio(customer.cpf, acao, this.blockMotivo).subscribe({
      next: (res) => {
        this.selectedCliente.set(res);
        this.blockMotivo = '';
        this.loadClientes(); // Reload list to update status
      }
    });
  }

  getContratoBadgeClass(codigo: string): string {
    // Return colors matching pawn statuses
    if (['RN', 'EMNV'].includes(codigo)) {
      return 'badge-success';
    }
    if (['AVAL', 'AVCL', 'LQ', 'LQDE', 'LQSD', 'LQVL', 'OBJA', 'SJLQ', 'ER', ''].includes(codigo)) {
      return 'badge-danger';
    }
    return 'badge-warning';
  }
}
