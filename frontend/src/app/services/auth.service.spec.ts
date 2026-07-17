import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { AuthService, UserState } from './auth.service';

describe('AuthService', () => {
  let httpMock: HttpTestingController;
  let routerSpy: any;

  beforeEach(() => {
    routerSpy = { navigate: vi.fn() };

    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AuthService,
        { provide: Router, useValue: routerSpy }
      ]
    });

    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should check authentication on init and set state if authenticated', () => {
    const service = TestBed.inject(AuthService);

    const mockState: UserState = { authenticated: true, is_staff: true, username: 'testuser' };
    const req = httpMock.expectOne('/api/auth/');
    expect(req.request.method).toBe('GET');
    req.flush(mockState);

    expect(service.isAuthenticated()).toBe(true);
    expect(service.currentUser()).toBe('testuser');
    expect(service.isLoading()).toBe(false);
  });

  it('should set authenticated to false if is_staff is false', () => {
    const service = TestBed.inject(AuthService);

    const mockState: UserState = { authenticated: true, is_staff: false, username: 'testuser' };
    const req = httpMock.expectOne('/api/auth/');
    req.flush(mockState);

    expect(service.isAuthenticated()).toBe(false);
    expect(service.currentUser()).toBeNull();
  });

  it('should handle auth check error gracefully', () => {
    const service = TestBed.inject(AuthService);

    const req = httpMock.expectOne('/api/auth/');
    req.error(new ErrorEvent('Network error'));

    expect(service.isAuthenticated()).toBe(false);
    expect(service.currentUser()).toBeNull();
    expect(service.isLoading()).toBe(false);
  });

  it('should login successfully and redirect', () => {
    const service = TestBed.inject(AuthService);

    // First flush the init GET request
    const initReq = httpMock.expectOne({ method: 'GET', url: '/api/auth/' });
    initReq.flush({ authenticated: false });

    service.login('admin', 'password').subscribe(success => {
      expect(success).toBe(true);
    });

    const req = httpMock.expectOne({ method: 'POST', url: '/api/auth/' });
    expect(req.request.body).toEqual({ action: 'login', username: 'admin', password: 'password' });
    req.flush({ authenticated: true, is_staff: true, username: 'admin' });

    expect(service.isAuthenticated()).toBe(true);
    expect(service.currentUser()).toBe('admin');
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/dashboard']);
  });

  it('should fail login if is_staff is false', () => {
    const service = TestBed.inject(AuthService);

    // First flush the init GET request
    const initReq = httpMock.expectOne({ method: 'GET', url: '/api/auth/' });
    initReq.flush({ authenticated: false });

    service.login('admin', 'password').subscribe(success => {
      expect(success).toBe(false);
    });

    const req = httpMock.expectOne({ method: 'POST', url: '/api/auth/' });
    req.flush({ authenticated: true, is_staff: false, username: 'admin' });

    expect(service.isAuthenticated()).toBe(false);
    expect(routerSpy.navigate).not.toHaveBeenCalled();
  });

  it('should return false on login error', () => {
    const service = TestBed.inject(AuthService);

    // First flush the init GET request
    const initReq = httpMock.expectOne({ method: 'GET', url: '/api/auth/' });
    initReq.flush({ authenticated: false });

    service.login('admin', 'password').subscribe(success => {
      expect(success).toBe(false);
    });

    const req = httpMock.expectOne({ method: 'POST', url: '/api/auth/' });
    req.error(new ErrorEvent('Unauthorized'));

    expect(service.isAuthenticated()).toBe(false);
  });

  it('should logout and redirect to login', () => {
    const service = TestBed.inject(AuthService);

    // First flush the init GET request
    const initReq = httpMock.expectOne({ method: 'GET', url: '/api/auth/' });
    initReq.flush({ authenticated: false });

    service.logout();

    const req = httpMock.expectOne({ method: 'POST', url: '/api/auth/' });
    expect(req.request.body).toEqual({ action: 'logout' });
    req.flush({});

    expect(service.isAuthenticated()).toBe(false);
    expect(service.currentUser()).toBeNull();
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/login']);
  });
});
