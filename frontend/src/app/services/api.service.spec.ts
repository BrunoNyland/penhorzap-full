import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ApiService } from './api.service';

describe('ApiService', () => {
  let service: ApiService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    service = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('getDashboardStats', () => {
    it('should GET /api/dashboard/', () => {
      const mockStats = { faqs_sugeridas_pendentes: 3 };

      service.getDashboardStats().subscribe(stats => {
        expect(stats).toEqual(mockStats);
      });

      const req = httpMock.expectOne('/api/dashboard/');
      expect(req.request.method).toBe('GET');
      req.flush(mockStats);
    });
  });

  describe('getBotConfig', () => {
    it('should GET /api/configs/bot/', () => {
      const mockConfig = { ativo: true };

      service.getBotConfig().subscribe(config => {
        expect(config).toEqual(mockConfig);
      });

      const req = httpMock.expectOne('/api/configs/bot/');
      expect(req.request.method).toBe('GET');
      req.flush(mockConfig);
    });
  });

  describe('updateBotConfig', () => {
    it('should PATCH /api/configs/bot/ with the given body', () => {
      const payload = { ativo: false, freshness_horas: 12 };

      service.updateBotConfig(payload).subscribe();

      const req = httpMock.expectOne('/api/configs/bot/');
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual(payload);
      req.flush({});
    });
  });

  describe('getMensagensConfig', () => {
    it('should GET /api/configs/mensagens/', () => {
      const mockConfig = { system_prompt: 'hello' };
      service.getMensagensConfig().subscribe(config => {
        expect(config).toEqual(mockConfig);
      });
      const req = httpMock.expectOne('/api/configs/mensagens/');
      expect(req.request.method).toBe('GET');
      req.flush(mockConfig);
    });
  });

  describe('updateMensagensConfig', () => {
    it('should PATCH /api/configs/mensagens/', () => {
      const payload = { msg_saudacao: 'Oi' };
      service.updateMensagensConfig(payload).subscribe();
      const req = httpMock.expectOne('/api/configs/mensagens/');
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual(payload);
      req.flush({});
    });
  });

  describe('restaurarMensagemCampo', () => {
    it('should POST /api/configs/mensagens/ with field', () => {
      service.restaurarMensagemCampo('msg_saudacao').subscribe();
      const req = httpMock.expectOne('/api/configs/mensagens/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ campo: 'msg_saudacao' });
      req.flush({});
    });
  });

  describe('getFAQs', () => {
    it('should GET /api/faqs/', () => {
      const mockFaqs = [{ id: 1, pergunta: 'Como funciona?' }];

      service.getFAQs().subscribe(faqs => {
        expect(faqs).toEqual(mockFaqs);
      });

      const req = httpMock.expectOne('/api/faqs/');
      expect(req.request.method).toBe('GET');
      req.flush(mockFaqs);
    });
  });

  describe('getFAQ', () => {
    it('should GET /api/faqs/{id}/', () => {
      service.getFAQ(5).subscribe();
      const req = httpMock.expectOne('/api/faqs/5/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });
  });

  describe('createFAQ', () => {
    it('should POST /api/faqs/ with body', () => {
      const payload = { pergunta: 'teste' };
      service.createFAQ(payload).subscribe();
      const req = httpMock.expectOne('/api/faqs/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual(payload);
      req.flush({});
    });
  });

  describe('updateFAQ', () => {
    it('should PUT /api/faqs/{id}/ with body', () => {
      const payload = { pergunta: 'teste' };
      service.updateFAQ(5, payload).subscribe();
      const req = httpMock.expectOne('/api/faqs/5/');
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual(payload);
      req.flush({});
    });
  });

  describe('deleteFAQ', () => {
    it('should DELETE /api/faqs/{id}/', () => {
      service.deleteFAQ(5).subscribe();
      const req = httpMock.expectOne('/api/faqs/5/');
      expect(req.request.method).toBe('DELETE');
      req.flush({});
    });
  });

  describe('toggleFAQ', () => {
    it('should POST to /api/faqs/{id}/toggle/ with an empty body', () => {
      service.toggleFAQ(7).subscribe();

      const req = httpMock.expectOne('/api/faqs/7/toggle/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({});
      req.flush({});
    });
  });

  describe('getConversas', () => {
    it('should GET /api/conversas/ without query params when no filters given', () => {
      service.getConversas().subscribe();

      const req = httpMock.expectOne(r => r.url === '/api/conversas/');
      expect(req.request.method).toBe('GET');
      expect(req.request.params.keys().length).toBe(0);
      req.flush([]);
    });

    it('should forward estado/revisao/q/tipo_contato as query params', () => {
      service.getConversas({
        estado: 'nova',
        revisao: 'sim',
        q: 'joao',
        tipo_contato: 'desconhecido'
      }).subscribe();

      const req = httpMock.expectOne(
        r => r.url === '/api/conversas/'
          && r.params.get('estado') === 'nova'
          && r.params.get('revisao') === 'sim'
          && r.params.get('q') === 'joao'
          && r.params.get('tipo_contato') === 'desconhecido'
      );
      expect(req.request.method).toBe('GET');
      req.flush([]);
    });
  });

  describe('getConversa', () => {
    it('should GET /api/conversas/{id}/', () => {
      service.getConversa(12).subscribe();
      const req = httpMock.expectOne('/api/conversas/12/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });
  });

  describe('toggleConversaRevisao', () => {
    it('should POST /api/conversas/{id}/toggle-revisao/', () => {
      service.toggleConversaRevisao(12).subscribe();
      const req = httpMock.expectOne('/api/conversas/12/toggle-revisao/');
      expect(req.request.method).toBe('POST');
      req.flush({});
    });
  });

  describe('limparTodasConversas', () => {
    it('should POST /api/conversas/limpar-todas/ with confirmacao body', () => {
      service.limparTodasConversas().subscribe();
      const req = httpMock.expectOne('/api/conversas/limpar-todas/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ confirmacao: 'DELETAR_TUDO' });
      req.flush({});
    });
  });

  describe('enviarMensagemConversa', () => {
    it('should POST /api/conversas/{id}/enviar/ with texto body', () => {
      service.enviarMensagemConversa(12, 'hello').subscribe();
      const req = httpMock.expectOne('/api/conversas/12/enviar/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ texto: 'hello' });
      req.flush({});
    });
  });

  describe('enviarArquivoConversa', () => {
    it('should POST /api/conversas/{id}/enviar-arquivo/ with FormData', () => {
      const fd = new FormData();
      service.enviarArquivoConversa(12, fd).subscribe();
      const req = httpMock.expectOne('/api/conversas/12/enviar-arquivo/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toBe(fd);
      req.flush({});
    });
  });

  describe('getFaqsSugeridas', () => {
    it('should GET /api/faqs-sugeridas/', () => {
      service.getFaqsSugeridas('pendente').subscribe();
      const req = httpMock.expectOne(r => r.url === '/api/faqs-sugeridas/' && r.params.get('status') === 'pendente');
      expect(req.request.method).toBe('GET');
      req.flush([]);
    });
  });

  describe('updateFaqSugerida', () => {
    it('should PATCH /api/faqs-sugeridas/{id}/', () => {
      const payload = { status: 'APROVADA' };
      service.updateFaqSugerida(5, payload).subscribe();
      const req = httpMock.expectOne('/api/faqs-sugeridas/5/');
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual(payload);
      req.flush({});
    });
  });

  describe('deleteFaqSugerida', () => {
    it('should DELETE /api/faqs-sugeridas/{id}/', () => {
      service.deleteFaqSugerida(5).subscribe();
      const req = httpMock.expectOne('/api/faqs-sugeridas/5/');
      expect(req.request.method).toBe('DELETE');
      req.flush({});
    });
  });

  describe('aprovarFaqSugerida', () => {
    it('should POST /api/faqs-sugeridas/{id}/aprovar/', () => {
      const payload = { pergunta_final: 'sim', respostas: [] };
      service.aprovarFaqSugerida(5, payload).subscribe();
      const req = httpMock.expectOne('/api/faqs-sugeridas/5/aprovar/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual(payload);
      req.flush({});
    });
  });

  describe('rejeitarFaqSugerida', () => {
    it('should POST /api/faqs-sugeridas/{id}/rejeitar/', () => {
      service.rejeitarFaqSugerida(5).subscribe();
      const req = httpMock.expectOne('/api/faqs-sugeridas/5/rejeitar/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({});
      req.flush({});
    });
  });

  describe('getClientes', () => {
    it('should GET /api/clientes/ with query filters', () => {
      service.getClientes({ q: 'joao', bloqueado: '1', ativos_somente: '1' }).subscribe();
      const req = httpMock.expectOne(
        r => r.url === '/api/clientes/'
          && r.params.get('q') === 'joao'
          && r.params.get('bloqueado') === '1'
          && r.params.get('ativos_somente') === '1'
      );
      expect(req.request.method).toBe('GET');
      req.flush([]);
    });
  });

  describe('getCliente', () => {
    it('should GET /api/clientes/{cpf}/', () => {
      service.getCliente('12345678901').subscribe();
      const req = httpMock.expectOne('/api/clientes/12345678901/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });
  });

  describe('toggleClienteBloqueio', () => {
    it('should POST /api/clientes/{cpf}/toggle-bloqueio/', () => {
      service.toggleClienteBloqueio('12345678901', 'bloquear', 'spam').subscribe();
      const req = httpMock.expectOne('/api/clientes/12345678901/toggle-bloqueio/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ acao: 'bloquear', motivo: 'spam' });
      req.flush({});
    });
  });

  describe('getWhatsappState', () => {
    it('should GET /api/whatsapp/state/', () => {
      service.getWhatsappState().subscribe();
      const req = httpMock.expectOne('/api/whatsapp/state/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });
  });

  describe('toggleWhatsappBot', () => {
    it('should POST to /api/whatsapp/state/ with an empty body', () => {
      service.toggleWhatsappBot().subscribe();

      const req = httpMock.expectOne('/api/whatsapp/state/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({});
      req.flush({ ativo: true });
    });
  });

  describe('getSimulatorState', () => {
    it('should GET /api/simulador/', () => {
      service.getSimulatorState().subscribe();
      const req = httpMock.expectOne('/api/simulador/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });
  });

  describe('postSimulatorAction', () => {
    it('should POST /api/simulador/ with action payload', () => {
      service.postSimulatorAction({ acao: 'mensagem', texto: 'oi' }).subscribe();
      const req = httpMock.expectOne('/api/simulador/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ acao: 'mensagem', texto: 'oi' });
      req.flush({});
    });
  });

  describe('getSolicitacoes', () => {
    it('should GET /api/solicitacoes/', () => {
      service.getSolicitacoes('pendente').subscribe();
      const req = httpMock.expectOne(r => r.url === '/api/solicitacoes/' && r.params.get('status') === 'pendente');
      expect(req.request.method).toBe('GET');
      req.flush([]);
    });
  });

  describe('uploadBoleto', () => {
    it('should POST FormData to /api/solicitacoes/{id}/boletos/', () => {
      const formData = new FormData();
      formData.append('pdf', new Blob(['dummy'], { type: 'application/pdf' }), 'boleto.pdf');
      formData.append('linha_digitavel', '00190.00009 01234.567890 12345.678901 1 23456789012345');

      service.uploadBoleto(42, formData).subscribe();

      const req = httpMock.expectOne('/api/solicitacoes/42/boletos/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toBe(formData);
      req.flush({});
    });
  });

  describe('uploadSqlite', () => {
    it('should POST /api/import/sqlite/ with FormData', () => {
      const fd = new FormData();
      service.uploadSqlite(fd).subscribe();
      const req = httpMock.expectOne('/api/import/sqlite/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toBe(fd);
      req.flush({});
    });
  });

  describe('getImportStatus', () => {
    it('should GET /api/import/sqlite/{id}/status/', () => {
      service.getImportStatus(12).subscribe();
      const req = httpMock.expectOne('/api/import/sqlite/12/status/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });
  });

  describe('getImportHistory', () => {
    it('should GET /api/import/sqlite/latest/', () => {
      service.getImportHistory().subscribe();
      const req = httpMock.expectOne('/api/import/sqlite/latest/');
      expect(req.request.method).toBe('GET');
      req.flush([]);
    });
  });
});
