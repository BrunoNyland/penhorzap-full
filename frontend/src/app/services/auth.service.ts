import { Injectable, signal, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, of } from 'rxjs';
import { catchError, map, tap } from 'rxjs/operators';

export interface UserState {
  authenticated: boolean;
  username?: string;
  is_staff?: boolean;
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  currentUser = signal<string | null>(null);
  isAuthenticated = signal<boolean>(false);
  isLoading = signal<boolean>(true);

  constructor() {
    this.checkAuth();
  }

  checkAuth(): void {
    this.isLoading.set(true);
    this.http.get<UserState>('/api/auth/')
      .pipe(
        tap(state => {
          if (state.authenticated && state.is_staff) {
            this.currentUser.set(state.username || 'Operador');
            this.isAuthenticated.set(true);
          } else {
            this.currentUser.set(null);
            this.isAuthenticated.set(false);
          }
          this.isLoading.set(false);
        }),
        catchError(() => {
          this.currentUser.set(null);
          this.isAuthenticated.set(false);
          this.isLoading.set(false);
          return of({ authenticated: false });
        })
      ).subscribe();
  }

  login(username: string, password: string): Observable<boolean> {
    return this.http.post<UserState>('/api/auth/', {
      action: 'login',
      username,
      password
    }).pipe(
      map(state => {
        if (state.authenticated && state.is_staff) {
          this.currentUser.set(state.username || username);
          this.isAuthenticated.set(true);
          this.router.navigate(['/dashboard']);
          return true;
        }
        return false;
      }),
      catchError(() => of(false))
    );
  }

  logout(): void {
    this.http.post('/api/auth/', { action: 'logout' })
      .pipe(
        catchError(() => of(null))
      ).subscribe(() => {
        this.currentUser.set(null);
        this.isAuthenticated.set(false);
        this.router.navigate(['/login']);
      });
  }
}
