import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="login-wrapper">
      <div class="login-card card">
        <div class="login-header">
          <div class="logo-circle">P</div>
          <h1>PenhorZap</h1>
          <p class="text-muted">Acesse o painel do operador</p>
        </div>

        <form (ngSubmit)="onSubmit()" #loginForm="ngForm">
          @if (errorMessage()) {
            <div class="error-banner">
              {{ errorMessage() }}
            </div>
          }

          <div class="form-group">
            <label for="username">Usuário</label>
            <input
              type="text"
              id="username"
              name="username"
              [(ngModel)]="username"
              required
              placeholder="Digite seu usuário"
              #usernameInput="ngModel"
            />
          </div>

          <div class="form-group">
            <label for="password">Senha</label>
            <input
              type="password"
              id="password"
              name="password"
              [(ngModel)]="password"
              required
              placeholder="Digite sua senha"
              #passwordInput="ngModel"
            />
          </div>

          <button
            type="submit"
            class="btn btn-primary login-btn"
            [disabled]="loginForm.invalid || isSubmitting()"
          >
            @if (isSubmitting()) {
              Entrando...
            } @else {
              Entrar
            }
          </button>
        </form>
      </div>
    </div>
  `,
  styles: [`
    .login-wrapper {
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      width: 100vw;
      background-color: var(--bg-primary);
      padding: 16px;
    }
    .login-card {
      max-width: 400px;
      width: 100%;
      padding: 32px;
    }
    .login-header {
      text-align: center;
      margin-bottom: 24px;
    }
    .login-header .logo-circle {
      margin: 0 auto 12px;
      width: 48px;
      height: 48px;
      font-size: 24px;
    }
    .login-header h1 {
      font-size: 24px;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .form-group {
      margin-bottom: 18px;
    }
    .form-group label {
      display: block;
      margin-bottom: 6px;
      font-weight: 500;
      color: var(--text-secondary);
    }
    .error-banner {
      background-color: var(--color-danger-bg);
      color: var(--color-danger);
      border: 1px solid rgba(239, 68, 68, 0.2);
      border-radius: var(--radius-sm);
      padding: 10px 12px;
      margin-bottom: 18px;
      font-size: 13px;
    }
    .login-btn {
      width: 100%;
      margin-top: 8px;
    }
  `]
})
export class LoginComponent {
  private authService = inject(AuthService);
  private router = inject(Router);

  username = '';
  password = '';
  isSubmitting = signal(false);
  errorMessage = signal<string | null>(null);

  constructor() {
    // If already logged in, redirect straight to dashboard
    if (this.authService.isAuthenticated()) {
      this.router.navigate(['/dashboard']);
    }
  }

  onSubmit(): void {
    if (!this.username || !this.password) return;
    this.isSubmitting.set(true);
    this.errorMessage.set(null);

    this.authService.login(this.username, this.password)
      .subscribe(success => {
        this.isSubmitting.set(false);
        if (!success) {
          this.errorMessage.set('Usuário ou senha inválidos ou permissão negada.');
        }
      });
  }
}
