import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { signal } from '@angular/core';
import { firstValueFrom, isObservable, Observable } from 'rxjs';

import { authGuard } from './auth.guard';
import { AuthService } from '../services/auth.service';

class MockAuthService {
    isLoading = signal(false);
    isAuthenticated = signal(false);
}

describe('authGuard', () => {
    let mockAuthService: MockAuthService;
    let router: Router;

    beforeEach(() => {
        mockAuthService = new MockAuthService();

        TestBed.configureTestingModule({
            providers: [
                { provide: AuthService, useValue: mockAuthService },
                { provide: Router, useValue: { navigate: vi.fn().mockName('navigate') } }
            ]
        });

        router = TestBed.inject(Router);
    });

    function runGuard(): boolean | Observable<boolean> {
        return TestBed.runInInjectionContext(() => authGuard({} as any, {} as any) as boolean | Observable<boolean>);
    }

    it('allows navigation when already authenticated and not loading', () => {
        mockAuthService.isLoading.set(false);
        mockAuthService.isAuthenticated.set(true);

        const result = runGuard();

        expect(result).toBe(true);
        expect(router.navigate).not.toHaveBeenCalled();
    });

    it('redirects to /login when not authenticated and not loading', () => {
        mockAuthService.isLoading.set(false);
        mockAuthService.isAuthenticated.set(false);

        const result = runGuard();

        expect(result).toBe(false);
        expect(router.navigate).toHaveBeenCalledWith(['/login']);
    });

    it('waits for isLoading to resolve, then allows navigation if authenticated', async () => {
        mockAuthService.isLoading.set(true);
        mockAuthService.isAuthenticated.set(false);

        const result = runGuard();
        expect(isObservable(result)).toBe(true);

        // Simulate checkAuth() resolving after the guard already subscribed.
        mockAuthService.isAuthenticated.set(true);
        mockAuthService.isLoading.set(false);

        const value = await firstValueFrom(result as Observable<boolean>);
        expect(value).toBe(true);
        expect(router.navigate).not.toHaveBeenCalled();
    });

    it('waits for isLoading to resolve, then redirects if still unauthenticated', async () => {
        mockAuthService.isLoading.set(true);
        mockAuthService.isAuthenticated.set(false);

        const result = runGuard();
        expect(isObservable(result)).toBe(true);

        mockAuthService.isLoading.set(false);

        const value = await firstValueFrom(result as Observable<boolean>);
        expect(value).toBe(false);
        expect(router.navigate).toHaveBeenCalledWith(['/login']);
    });
});
