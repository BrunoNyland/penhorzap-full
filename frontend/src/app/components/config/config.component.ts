import { Component, inject, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-config',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="config-wrapper">
      <div class="config-header flex align-center justify-between">
        <div>
          <h1>Configurações do Sistema</h1>
          <p class="text-muted">Ajuste o comportamento do bot, regras operacionais e prompt da IA</p>
        </div>
      </div>

      <!-- Tab Navigation -->
      <div class="tabs flex gap-2">
        <button 
          class="tab-btn" 
          [class.active]="activeTab() === 'bot'" 
          (click)="activeTab.set('bot')"
        >
          Parâmetros do Bot
        </button>
        <button 
          class="tab-btn" 
          [class.active]="activeTab() === 'prompt'" 
          (click)="activeTab.set('prompt')"
        >
          Prompt do Gemini
        </button>
        <button 
          class="tab-btn" 
          [class.active]="activeTab() === 'mensagens'" 
          (click)="activeTab.set('mensagens')"
        >
          Textos & Respostas Fixas
        </button>
      </div>

      <!-- Notification banner -->
      @if (toastMessage()) {
        <div class="toast-banner" [class.success]="toastType() === 'success'" [class.error]="toastType() === 'error'">
          {{ toastMessage() }}
        </div>
      }

      <!-- Tab: Bot Config -->
      @if (activeTab() === 'bot') {
        <div class="card fade-in">
          <h2>Regras Operacionais</h2>
          <p class="text-muted margin-bottom">Knobs operacionais de ativação e sincronização.</p>

          <form (ngSubmit)="saveBotConfig()">
            <div class="form-group margin-bottom">
              <label class="checkbox-container">
                <input type="checkbox" name="ativo" [(ngModel)]="botConfig.ativo" />
                <span class="custom-checkbox"></span>
                <span><strong>Bot Ativo</strong> (Permite processamento e respostas automáticas no WhatsApp)</span>
              </label>
            </div>

            <div class="form-group margin-bottom">
              <label class="checkbox-container">
                <input type="checkbox" name="responder_desconhecidos" [(ngModel)]="botConfig.responder_desconhecidos" />
                <span class="custom-checkbox"></span>
                <span><strong>Responder Desconhecidos</strong> (Saúda números que não estão na agenda)</span>
              </label>
            </div>

            <div class="grid-2">
              <div class="form-group">
                <label for="horario_encerramento">Horário de Encerramento Automático</label>
                <input 
                  type="time" 
                  id="horario_encerramento" 
                  name="horario_encerramento" 
                  [(ngModel)]="botConfig.horario_encerramento" 
                />
                <span class="help-text">Desativa o bot automaticamente no horário selecionado (fuso SP).</span>
              </div>

              <div class="form-group">
                <label for="freshness_horas">Validade dos Dados ERP (Horas)</label>
                <input 
                  type="number" 
                  id="freshness_horas" 
                  name="freshness_horas" 
                  min="1" 
                  [(ngModel)]="botConfig.freshness_horas" 
                />
                <span class="help-text">Tempo máximo aceitável após o último import do SQLite.</span>
              </div>
            </div>

            <div class="grid-2 margin-top">
              <div class="form-group">
                <label for="dias_resgate_garantia">Dias de Resgate da Garantia</label>
                <input 
                  type="number" 
                  id="dias_resgate_garantia" 
                  name="dias_resgate_garantia" 
                  min="1" 
                  [(ngModel)]="botConfig.dias_resgate_garantia" 
                />
                <span class="help-text">Dias após a quitação para liberar o agendamento de retirada de joias.</span>
              </div>

              <div class="form-group flex align-center label-only">
                <p class="text-muted">
                  Última atualização de dados: <strong class="text-primary">{{ formatDateTime(botConfig.ultima_atualizacao_dados) }}</strong>
                </p>
              </div>
            </div>

            <div class="form-actions margin-top">
              <button type="submit" class="btn btn-primary" [disabled]="saving()">
                {{ saving() ? 'Salvando...' : 'Salvar Alterações' }}
              </button>
            </div>
          </form>
        </div>
      }

      <!-- Tab: Prompt Config -->
      @if (activeTab() === 'prompt') {
        <div class="card fade-in">
          <div class="flex justify-between align-center">
            <h2>Instruções do Sistema (System Prompt)</h2>
            <button class="btn btn-secondary btn-small" (click)="restoreField('system_prompt')">Restaurar Padrão</button>
          </div>
          <p class="text-muted margin-bottom">Define o papel, a personalidade da IA, as restrições de cálculo e regras de privacidade.</p>

          <form (ngSubmit)="saveMensagensConfig()">
            <div class="form-group">
              <textarea 
                name="system_prompt" 
                rows="18" 
                class="code-editor"
                [(ngModel)]="mensagensConfig.system_prompt"
              ></textarea>
            </div>

            <div class="form-actions margin-top">
              <button type="submit" class="btn btn-primary" [disabled]="saving()">
                {{ saving() ? 'Salvando...' : 'Salvar Prompt' }}
              </button>
            </div>
          </form>
        </div>
      }

      <!-- Tab: Mensagens Config -->
      @if (activeTab() === 'mensagens') {
        <div class="card fade-in">
          <h2>Mensagens Fixas e Fallbacks</h2>
          <p class="text-muted margin-bottom">Configure os retornos automáticos e gatilhos de interação do bot.</p>

          <form (ngSubmit)="saveMensagensConfig()">
            <div class="msg-editor-list">
              @for (field of camposMensagens; track field.key) {
                <div class="msg-editor-row card">
                  <div class="flex justify-between align-center margin-bottom-sm">
                    <div>
                      <strong class="field-title">{{ field.label }}</strong>
                      <span class="field-key">({{ field.key }})</span>
                    </div>
                    <button type="button" class="btn btn-secondary btn-small" (click)="restoreField(field.key)">
                      Restaurar Padrão
                    </button>
                  </div>
                  <textarea 
                    [name]="field.key" 
                    [(ngModel)]="mensagensConfig[field.key]"
                    rows="3"
                  ></textarea>
                  <span class="help-text">{{ field.help }}</span>
                </div>
              }
            </div>

            <div class="form-actions margin-top">
              <button type="submit" class="btn btn-primary" [disabled]="saving()">
                {{ saving() ? 'Salvando...' : 'Salvar Mensagens' }}
              </button>
            </div>
          </form>
        </div>
      }
    </div>
  `,
  styles: [`
    .config-wrapper {
      display: flex;
      flex-direction: column;
      gap: 24px;
    }
    .config-header h1 {
      font-size: 26px;
      font-weight: 700;
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
      padding: 12px 18px;
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
    .margin-bottom {
      margin-bottom: 20px;
    }
    .margin-bottom-sm {
      margin-bottom: 10px;
    }
    .margin-top {
      margin-top: 20px;
    }
    .grid-2 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 20px;
    }
    .help-text {
      font-size: 12px;
      color: var(--text-muted);
      display: block;
      margin-top: 4px;
    }
    .code-editor {
      font-family: 'Courier New', Courier, monospace;
      font-size: 13px;
      line-height: 1.6;
      background-color: #0d1117;
      color: #c9d1d9;
    }
    .toast-banner {
      padding: 14px 16px;
      border-radius: var(--radius-md);
      font-weight: 500;
      font-size: 14px;
    }
    .toast-banner.success {
      background-color: var(--color-success-bg);
      color: var(--color-success);
      border: 1px solid rgba(16, 185, 129, 0.2);
    }
    .toast-banner.error {
      background-color: var(--color-danger-bg);
      color: var(--color-danger);
      border: 1px solid rgba(239, 68, 68, 0.2);
    }
    .msg-editor-list {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .msg-editor-row {
      padding: 16px;
      background-color: var(--bg-surface);
    }
    .field-title {
      font-size: 14px;
      color: var(--text-primary);
    }
    .field-key {
      font-size: 11px;
      color: var(--text-muted);
      margin-left: 6px;
    }
    .btn-small {
      padding: 6px 12px;
      font-size: 12px;
    }
    .fade-in {
      animation: fadeIn 0.2s ease-out;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .label-only {
      padding-top: 24px;
    }

    @media (max-width: 639px) {
      .config-header h1 {
        font-size: 22px;
      }
      .tabs {
        flex-wrap: wrap;
        gap: 6px;
      }
      .tab-btn {
        flex: 1 1 auto;
        padding: 10px 12px;
        font-size: 13px;
        text-align: center;
      }
      .grid-2 {
        grid-template-columns: 1fr;
      }
      .code-editor {
        font-size: 14px;
      }
    }
  `]
})
export class ConfigComponent implements OnInit {
  private apiService = inject(ApiService);

  activeTab = signal<'bot' | 'prompt' | 'mensagens'>('bot');
  loading = signal(false);
  saving = signal(false);

  toastMessage = signal<string | null>(null);
  toastType = signal<'success' | 'error'>('success');

  botConfig: any = {};
  mensagensConfig: any = {};

  camposMensagens = [
    { key: 'msg_saudacao', label: 'Saudação (Desconhecido)', help: 'Saudação inicial p/ contatos não salvos na agenda. Use a tag {saudacao}.' },
    { key: 'msg_cadastro_nao_localizado', label: 'Cadastro não localizado', help: 'Retorno enviado quando o CPF fornecido não está na base de dados.' },
    { key: 'msg_pedir_cpf', label: 'Pedir CPF', help: 'Mensagem solicitando que o usuário digite seu CPF.' },
    { key: 'msg_cpf_invalido', label: 'CPF Inválido', help: 'Erro retornado se o CPF falhar na validação do dígito verificador.' },
    { key: 'msg_cpf_nao_bate', label: 'CPF Não Confere', help: 'Mensagem de erro quando o CPF digitado difere do CPF registrado p/ aquele contato.' },
    { key: 'msg_verificacao_ok', label: 'Verificação OK', help: 'Confirmação de que o CPF foi digitado com sucesso e os dados combinam.' },
    { key: 'msg_verificacao_falhou', label: 'Verificação Falhou', help: 'Fallback enviado se a verificação expirar ou falhar seguidamente.' },
    { key: 'msg_sem_info_faq', label: 'Sem Informação na FAQ', help: 'Enviado quando o cliente faz uma pergunta geral que o bot não encontra na base.' },
    { key: 'msg_db_desatualizada', label: 'Base de dados Desatualizada', help: 'Erro emitido ao pedir informações financeiras se a base do ERP estiver fora do freshness.' },
    { key: 'msg_sem_contratos_actifs', label: 'Sem Contratos Ativos', help: 'Retorno quando o cliente verificado não possui contratos ativos em aberto.' },
    { key: 'msg_solicitacao_criada', label: 'Solicitação Criada', help: 'Confirmando a abertura da solicitação para envio dos boletos.' },
    { key: 'msg_boleto_intro', label: 'Introdução do Boleto', help: 'Introdução enviada imediatamente antes de anexar o PDF do boleto.' },
    { key: 'msg_renovacao_proximo_vencimento', label: 'Renovação: Próximo Vencimento', help: 'Usa a tag {proximo_vencimento}.' },
    { key: 'msg_quitacao_garantia', label: 'Quitação: Resgate de Garantia', help: 'Instrução para retirada de bens. Usa a tag {data_resgate}.' },
    { key: 'msg_segunda_via_confirma', label: 'Confirmação de 2ª via', help: 'Usa as tags {contratos} e {tipo}.' },
    { key: 'msg_insistiu_humano', label: 'Insistiu por Humano', help: 'Feedback enviado se o usuário repetir comandos de fallback sucessivamente.' },
    { key: 'msg_neutra_padrao', label: 'Mensagem Neutra Padrão', help: 'Conversa genérica sem intenção identificável.' }
  ];

  ngOnInit(): void {
    this.loadConfigs();
  }

  loadConfigs(): void {
    this.loading.set(true);
    this.apiService.getBotConfig().subscribe(res => {
      this.botConfig = res;
    });

    this.apiService.getMensagensConfig().subscribe(res => {
      this.mensagensConfig = res;
      this.loading.set(false);
    });
  }

  saveBotConfig(): void {
    this.saving.set(true);
    this.apiService.updateBotConfig(this.botConfig).subscribe({
      next: (res) => {
        this.botConfig = res;
        this.showToast('Configuração do bot atualizada com sucesso!', 'success');
        this.saving.set(false);
      },
      error: () => {
        this.showToast('Falha ao salvar configuração.', 'error');
        this.saving.set(false);
      }
    });
  }

  saveMensagensConfig(): void {
    this.saving.set(true);
    this.apiService.updateMensagensConfig(this.mensagensConfig).subscribe({
      next: (res) => {
        this.mensagensConfig = res;
        this.showToast('Prompts & Mensagens salvos com sucesso!', 'success');
        this.saving.set(false);
      },
      error: () => {
        this.showToast('Falha ao salvar textos.', 'error');
        this.saving.set(false);
      }
    });
  }

  restoreField(campo: string): void {
    if (confirm(`Tem certeza que deseja restaurar o campo '${campo}' ao padrão do sistema?`)) {
      this.apiService.restaurarMensagemCampo(campo).subscribe({
        next: (res) => {
          this.mensagensConfig = res;
          this.showToast(`Campo ${campo} restaurado ao padrão de fábrica!`, 'success');
        },
        error: () => {
          this.showToast('Erro ao restaurar campo.', 'error');
        }
      });
    }
  }

  showToast(msg: string, type: 'success' | 'error'): void {
    this.toastMessage.set(msg);
    this.toastType.set(type);
    setTimeout(() => {
      this.toastMessage.set(null);
    }, 4000);
  }

  formatDateTime(dateStr: string): string {
    if (!dateStr) return 'Nunca';
    return new Date(dateStr).toLocaleString('pt-BR');
  }
}
