import { Component, inject, effect, signal } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive, NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs/operators';
import { AuthService } from './services/auth.service';
import { ApiService } from './services/api.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent {
  authService = inject(AuthService);
  private apiService = inject(ApiService);
  private router = inject(Router);
  theme = 'dark';

  // Sidebar mobile (< 640px): menu hamburguer com overlay.
  // Off-canvas por padrão; abre por cima do conteúdo quando acionado.
  sidebarOpen = signal(false);

  // Badge de FAQs sugeridas pendentes de curadoria (item de menu "FAQs & Respostas").
  faqsSugeridasPendentes = signal(0);

  constructor() {
    // Read theme from localStorage or default to dark
    const savedTheme = localStorage.getItem('theme') || 'dark';
    this.setTheme(savedTheme);

    // Carrega a contagem assim que o usuário autentica; sem polling novo,
    // só reaproveita o GET leve do dashboard já usado no sistema.
    effect(() => {
      if (this.authService.isAuthenticated()) {
        this.loadFaqsSugeridasPendentes();
      }
    });

    // Fecha o menu mobile automaticamente ao navegar para outra rota, e
    // atualiza o badge de sugestões (cobre o caso de aprovar/rejeitar numa
    // navegação e voltar para outra tela).
    this.router.events
      .pipe(filter((event): event is NavigationEnd => event instanceof NavigationEnd))
      .subscribe(() => {
        this.sidebarOpen.set(false);
        if (this.authService.isAuthenticated()) {
          this.loadFaqsSugeridasPendentes();
        }
      });
  }

  private loadFaqsSugeridasPendentes(): void {
    this.apiService.getDashboardStats().subscribe({
      next: (res) => this.faqsSugeridasPendentes.set(res?.faqs_sugeridas_pendentes || 0),
      error: () => {}
    });
  }

  toggleSidebar(): void {
    this.sidebarOpen.update(v => !v);
  }

  closeSidebar(): void {
    this.sidebarOpen.set(false);
  }

  toggleTheme(): void {
    const nextTheme = this.theme === 'dark' ? 'light' : 'dark';
    this.setTheme(nextTheme);
  }

  private setTheme(theme: string): void {
    this.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }

  logout(): void {
    this.authService.logout();
  }
}
