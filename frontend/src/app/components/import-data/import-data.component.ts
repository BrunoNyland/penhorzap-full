import { Component, inject, signal, OnInit, OnDestroy, ChangeDetectionStrategy } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-import-data',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './import-data.component.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './import-data.component.css'
})
export class ImportDataComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);

  loading = signal(false);
  polling = signal(false);
  jobId = signal<number | null>(null);
  status = signal<string>('');
  counts = signal<any>(null);
  erro = signal<string>('');
  arquivoNome = signal<string>('');
  historico = signal<any[]>([]);

  selectedFile: File | null = null;

  private pollInterval: any;

  ngOnInit(): void {
    this.carregarHistorico();
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.selectedFile = input.files[0];
      this.arquivoNome.set(this.selectedFile.name);
    }
  }

  onUpload(): void {
    if (!this.selectedFile || this.loading() || this.polling()) return;
    if (!confirm(`Importar "${this.selectedFile.name}" agora vai sobrescrever os dados atuais de clientes, contratos, agências e licitações. Continuar?`)) {
      return;
    }

    const formData = new FormData();
    formData.append('arquivo', this.selectedFile, this.selectedFile.name);

    this.loading.set(true);
    this.status.set('pendente');
    this.counts.set(null);
    this.erro.set('');

    this.api.uploadSqlite(formData).subscribe({
      next: (res) => {
        this.loading.set(false);
        this.jobId.set(res.id);
        this.status.set(res.status);
        this.startPolling();
      },
      error: () => {
        this.loading.set(false);
        this.status.set('falhou');
        this.erro.set('Falha ao enviar o arquivo.');
      }
    });
  }

  private startPolling(): void {
    this.stopPolling();
    this.polling.set(true);
    this.pollInterval = setInterval(() => this.fetchStatus(), 2000);
  }

  private stopPolling(): void {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    this.polling.set(false);
  }

  private fetchStatus(): void {
    const id = this.jobId();
    if (id === null) return;

    this.api.getImportStatus(id).subscribe({
      next: (res) => {
        this.status.set(res.status);
        if (res.status === 'concluido') {
          this.counts.set(res.counts);
          this.stopPolling();
          this.carregarHistorico();
        } else if (res.status === 'falhou') {
          this.erro.set(res.erro || 'Erro desconhecido.');
          this.stopPolling();
          this.carregarHistorico();
        }
      },
      error: () => {
        this.stopPolling();
        this.status.set('falhou');
        this.erro.set('Falha ao consultar o status da importação.');
      }
    });
  }

  carregarHistorico(): void {
    this.api.getImportHistory().subscribe({
      next: (data) => {
        this.historico.set(data);
      }
    });
  }

  statusBadgeClass(status: string): string {
    if (status === 'concluido') return 'status-badge success';
    if (status === 'falhou') return 'status-badge failed';
    return 'status-badge pending';
  }

  statusLabel(status: string): string {
    const labels: { [key: string]: string } = {
      pendente: 'Pendente',
      andamento: 'Em andamento',
      concluido: 'Concluído',
      falhou: 'Falhou'
    };
    return labels[status] || status;
  }

  readonly countRows = [
    { key: 'agencias_penhor', label: 'Agências' },
    { key: 'licitacoes', label: 'Licitações' },
    { key: 'clientes', label: 'Clientes' },
    { key: 'telefones', label: 'Telefones' },
    { key: 'contratos', label: 'Contratos' }
  ];
}