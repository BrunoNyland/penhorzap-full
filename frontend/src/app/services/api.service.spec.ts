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

  describe('toggleFAQ', () => {
    it('should POST to /api/faqs/{id}/toggle/ with an empty body', () => {
      service.toggleFAQ(7).subscribe();

      const req = httpMock.expectOne('/api/faqs/7/toggle/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({});
      req.flush({});
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

  describe('toggleWhatsappBot', () => {
    it('should POST to /api/whatsapp/state/ with an empty body', () => {
      service.toggleWhatsappBot().subscribe();

      const req = httpMock.expectOne('/api/whatsapp/state/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({});
      req.flush({ ativo: true });
    });
  });
});
