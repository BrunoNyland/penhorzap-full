import { Component, inject, signal, computed, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { IconComponent } from '../../shared/icon/icon.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [DecimalPipe, IconComponent],
  template: `
    <div class="dashboard-wrapper">
      <div class="dashboard-header flex align-center justify-between">
        <div>
          <h1>Dashboard Operacional</h1>
          <p class="text-muted">Visão geral dos atendimentos, boletos e estatísticas da IA</p>
        </div>
        <button class="btn btn-secondary" (click)="loadStats()" [disabled]="loading()">
          @if (loading()) {
            Atualizando...
          } @else {
            Atualizar Dados
          }
        </button>
      </div>

      @if (loading() && !stats()) {
        <div class="loading-container">
          <div class="spinner"></div>
          <p>Carregando métricas...</p>
        </div>
      } @else if (stats()) {
        <!-- Grid de KPI Counters -->
        <div class="kpi-grid">
          <div class="kpi-card card">
            <div class="kpi-header flex justify-between">
              <span class="text-muted">Total de Clientes</span>
              <span class="kpi-icon"><app-icon name="users" [size]="20"></app-icon></span>
            </div>
            <div class="kpi-val">{{ stats().total_clientes | number }}</div>
            <div class="kpi-sub text-muted">
              {{ stats().clientes_com_telefone | number }} com whats • {{ stats().clientes_bloqueados | number }} bloqueados IA
            </div>
          </div>

          <div class="kpi-card card">
            <div class="kpi-header flex justify-between">
              <span class="text-muted">Total de Conversas</span>
              <span class="kpi-icon"><app-icon name="message-circle" [size]="20"></app-icon></span>
            </div>
            <div class="kpi-val">{{ stats().total_conversas | number }}</div>
            <div class="kpi-sub text-danger" [class.text-success]="stats().conversas_precisa_revisao === 0">
              <app-icon name="alert-triangle" [size]="12"></app-icon> {{ stats().conversas_precisa_revisao | number }} precisam de revisão ({{ stats().taxa_conversas_revisao | number:'1.1-1' }}%)
            </div>
          </div>

          <div class="kpi-card card">
            <div class="kpi-header flex justify-between">
              <span class="text-muted">Solicitações de Boletos</span>
              <span class="kpi-icon"><app-icon name="clipboard-list" [size]="20"></app-icon></span>
            </div>
            <div class="kpi-val">{{ stats().total_solicitacoes | number }}</div>
            <div class="kpi-sub text-warning">
              <app-icon name="alert-triangle" [size]="12"></app-icon> {{ stats().solicitacoes_precisa_humano | number }} enviadas para humano ({{ stats().taxa_solicitacoes_humano | number:'1.1-1' }}%)
            </div>
          </div>

          <div class="kpi-card card">
            <div class="kpi-header flex justify-between">
              <span class="text-muted">Boletos Gerados</span>
              <span class="kpi-icon"><app-icon name="dollar-sign" [size]="20"></app-icon></span>
            </div>
            <div class="kpi-val">{{ stats().total_boletos | number }}</div>
            <div class="kpi-sub text-success">
              <app-icon name="check" [size]="12"></app-icon> {{ stats().boletos_enviados | number }} enviados ao cliente
            </div>
          </div>
        </div>

        <!-- Linha de Gráficos Principais -->
        <div class="charts-row">
          <!-- Gráfico SVG de Linhas do Volume de 30 Dias -->
          <div class="chart-container card flex-2">
            <h2>Volume de Mensagens (Últimos 30 dias)</h2>
            <p class="text-muted text-small">Tráfego de mensagens recebidas (verde) vs. enviadas (azul)</p>
            
            <div class="svg-chart-wrapper">
              <svg [attr.viewBox]="'0 0 ' + svgWidth + ' ' + svgHeight" class="svg-line-chart">
                <!-- Grid Lines -->
                @for (gridY of [0, 0.25, 0.5, 0.75, 1]; track gridY) {
                  <line 
                    x1="40" 
                    [attr.y1]="svgHeight - 40 - gridY * (svgHeight - 60)" 
                    [attr.x2]="svgWidth - 20" 
                    [attr.y2]="svgHeight - 40 - gridY * (svgHeight - 60)"
                    stroke="var(--border-color)" 
                    stroke-width="1" 
                    stroke-dasharray="4"
                  />
                  <text 
                    x="5" 
                    [attr.y]="svgHeight - 36 - gridY * (svgHeight - 60)" 
                    fill="var(--text-muted)" 
                    font-size="10"
                  >
                    {{ (maxVal() * gridY) | number:'1.0-0' }}
                  </text>
                }

                <!-- Lines Paths -->
                <path 
                  [attr.d]="receivedPath()" 
                  fill="none" 
                  stroke="var(--color-success)" 
                  stroke-width="3" 
                  stroke-linecap="round" 
                  stroke-linejoin="round"
                />
                <path 
                  [attr.d]="sentPath()" 
                  fill="none" 
                  stroke="var(--color-accent)" 
                  stroke-width="3" 
                  stroke-linecap="round" 
                  stroke-linejoin="round"
                />

                <!-- Interactive hover nodes -->
                @for (d of serie(); track i; let i = $index) {
                  <g class="chart-node-group">
                    <!-- Received dot -->
                    <circle 
                      [attr.cx]="getNodeX(i)" 
                      [attr.cy]="getNodeY(d.recebidas)" 
                      r="4" 
                      fill="var(--color-success)"
                    />
                    <!-- Sent dot -->
                    <circle 
                      [attr.cx]="getNodeX(i)" 
                      [attr.cy]="getNodeY(d.enviadas)" 
                      r="4" 
                      fill="var(--color-accent)"
                    />
                    <!-- Tooltip overlay -->
                    <rect 
                      [attr.x]="getNodeX(i) - 15" 
                      y="10" 
                      width="30" 
                      [attr.height]="svgHeight - 30" 
                      fill="transparent"
                      class="hover-trigger"
                    >
                      <title>{{ formatDate(d.dia) }}: In: {{ d.recebidas }} | Out: {{ d.enviadas }}</title>
                    </rect>
                  </g>
                }
              </svg>
            </div>
            
            <div class="legend flex gap-4 justify-center">
              <span class="legend-item"><span class="legend-color success"></span> Recebidas</span>
              <span class="legend-item"><span class="legend-color accent"></span> Enviadas</span>
            </div>
          </div>

          <!-- Sazonalidade por dia da semana -->
          <div class="chart-container card flex-1">
            <h2>Mensagens por Dia (180d)</h2>
            <p class="text-muted text-small">Volume acumulado por dia da semana</p>
            
            <div class="bar-chart-container">
              @for (day of porDiaSemana(); track day.label) {
                <div class="bar-item">
                  <div class="bar-label">{{ day.label }}</div>
                  <div class="bar-wrapper">
                    <div 
                      class="bar-fill" 
                      [style.width.%]="(day.total / maxSemana()) * 100"
                      [title]="day.total + ' mensagens'"
                    ></div>
                  </div>
                  <div class="bar-value">{{ day.total | number }}</div>
                </div>
              }
            </div>
          </div>
        </div>

        <!-- Seção: Solicitações por Tipo & Status -->
        <div class="distributions-grid">
          <div class="card">
            <h2>Tipos de Solicitações</h2>
            <div class="distribution-list">
              @for (t of stats().por_tipo; track t.tipo) {
                <div class="dist-row">
                  <div class="dist-info flex justify-between">
                    <span>{{ t.label }}</span>
                    <strong>{{ t.total }}</strong>
                  </div>
                  <div class="dist-bar-bg">
                    <div class="dist-bar-fill" [style.width.%]="(t.total / stats().total_solicitacoes) * 100"></div>
                  </div>
                </div>
              } @empty {
                <p class="text-muted">Nenhuma solicitação criada ainda.</p>
              }
            </div>
          </div>

          <div class="card">
            <h2>Status das Solicitações</h2>
            <div class="distribution-list">
              @for (s of stats().por_status; track s.status) {
                <div class="dist-row">
                  <div class="dist-info flex justify-between">
                    <span>{{ s.label }}</span>
                    <strong>{{ s.total }}</strong>
                  </div>
                  <div class="dist-bar-bg">
                    <div class="dist-bar-fill accent" [style.width.%]="(s.total / stats().total_solicitacoes) * 100"></div>
                  </div>
                </div>
              } @empty {
                <p class="text-muted">Nenhuma solicitação criada ainda.</p>
              }
            </div>
          </div>
        </div>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.Eager,
  styles: [`
    .dashboard-wrapper {
      display: flex;
      flex-direction: column;
      gap: 24px;
    }
    .dashboard-header h1 {
      font-size: 26px;
      font-weight: 700;
    }
    .loading-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 64px 0;
      gap: 16px;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 20px;
    }
    .kpi-card {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .kpi-header {
      font-size: 13px;
      font-weight: 500;
    }
    .kpi-val {
      font-size: 32px;
      font-weight: 700;
      color: var(--text-primary);
    }
    .kpi-sub {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
    }
    .charts-row {
      display: flex;
      gap: 24px;
      flex-wrap: wrap;
    }
    .chart-container {
      min-width: 300px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .flex-2 { flex: 2; }
    .flex-1 { flex: 1; }
    .svg-chart-wrapper {
      position: relative;
      background-color: var(--bg-primary);
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-color);
      padding: 10px;
    }
    .svg-line-chart {
      width: 100%;
      height: 100%;
      display: block;
    }
    .chart-node-group circle {
      opacity: 0;
      transition: opacity var(--transition-fast);
    }
    .chart-node-group:hover circle {
      opacity: 1;
    }
    .hover-trigger {
      cursor: crosshair;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--text-secondary);
    }
    .legend-color {
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }
    .legend-color.success { background-color: var(--color-success); }
    .legend-color.accent { background-color: var(--color-accent); }
    
    .bar-chart-container {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-top: 12px;
    }
    .bar-item {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 13px;
    }
    .bar-label {
      width: 70px;
      color: var(--text-secondary);
      font-weight: 500;
    }
    .bar-wrapper {
      flex: 1;
      height: 8px;
      background-color: var(--bg-primary);
      border-radius: 9999px;
      overflow: hidden;
    }
    .bar-fill {
      height: 100%;
      background-color: var(--color-accent);
      border-radius: 9999px;
    }
    .bar-value {
      width: 40px;
      text-align: right;
      font-weight: 600;
      color: var(--text-primary);
    }

    .distributions-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 24px;
    }
    .distribution-list {
      display: flex;
      flex-direction: column;
      gap: 16px;
      margin-top: 16px;
    }
    .dist-row {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .dist-info {
      font-size: 13px;
      color: var(--text-secondary);
    }
    .dist-bar-bg {
      height: 6px;
      background-color: var(--bg-primary);
      border-radius: 9999px;
      overflow: hidden;
    }
    .dist-bar-fill {
      height: 100%;
      background-color: var(--color-success);
      border-radius: 9999px;
    }
    .dist-bar-fill.accent {
      background-color: var(--color-accent);
    }
    .text-small {
      font-size: 12px;
    }

    @media (max-width: 639px) {
      .dashboard-header h1 {
        font-size: 22px;
      }
      .dashboard-header button {
        width: 100%;
      }
      .kpi-grid, .distributions-grid {
        grid-template-columns: 1fr;
      }
      .charts-row {
        flex-direction: column;
      }
      .chart-container {
        min-width: 0;
        width: 100%;
      }
      .bar-label {
        width: 56px;
      }
    }
  `]
})
export class DashboardComponent implements OnInit {
  private apiService = inject(ApiService);

  stats = signal<any>(null);
  loading = signal(false);

  svgWidth = 800;
  svgHeight = 250;

  maxVal = computed(() => this.stats()?.maior_valor_serie || 100);
  serie = computed(() => this.stats()?.serie_30_dias || []);

  maxSemana = computed(() => this.stats()?.maior_valor_semana || 1);
  porDiaSemana = computed(() => this.stats()?.por_dia_semana || []);

  receivedPath = computed(() => {
    const data = this.serie();
    if (data.length === 0) return '';
    return data.map((d: any, i: number) => {
      const x = this.getNodeX(i);
      const y = this.getNodeY(d.recebidas);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    }).join(' ');
  });

  sentPath = computed(() => {
    const data = this.serie();
    if (data.length === 0) return '';
    return data.map((d: any, i: number) => {
      const x = this.getNodeX(i);
      const y = this.getNodeY(d.enviadas);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    }).join(' ');
  });

  ngOnInit(): void {
    this.loadStats();
  }

  loadStats(): void {
    this.loading.set(true);
    this.apiService.getDashboardStats().subscribe({
      next: (res) => {
        this.stats.set(res);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      }
    });
  }

  getNodeX(index: number): number {
    const dataLength = this.serie().length;
    if (dataLength <= 1) return 45;
    return (index / (dataLength - 1)) * (this.svgWidth - 60) + 45;
  }

  getNodeY(val: number): number {
    const max = this.maxVal();
    return this.svgHeight - (val / max) * (this.svgHeight - 60) - 40;
  }

  formatDate(dateStr: string): string {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    if (parts.length < 3) return dateStr;
    return `${parts[2]}/${parts[1]}`;
  }
}
