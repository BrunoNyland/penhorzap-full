import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { unsavedChangesGuard } from './guards/unsaved-changes.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./components/login/login.component').then(m => m.LoginComponent)
  },
  {
    path: '',
    canActivate: [authGuard],
    children: [
      {
        path: 'dashboard',
        loadComponent: () => import('./components/dashboard/dashboard.component').then(m => m.DashboardComponent)
      },
      {
        path: 'faqs',
        loadComponent: () => import('./components/faq/faq.component').then(m => m.FAQComponent)
      },
      {
        path: 'conversations',
        loadComponent: () => import('./components/conversations/conversations.component').then(m => m.ConversationsComponent)
      },
      {
        path: 'customers',
        loadComponent: () => import('./components/customers/customers.component').then(m => m.CustomersComponent)
      },
      {
        path: 'config',
        loadComponent: () => import('./components/config/config.component').then(m => m.ConfigComponent),
        canDeactivate: [unsavedChangesGuard]
      },
      {
        path: 'whatsapp',
        loadComponent: () => import('./components/whatsapp/whatsapp.component').then(m => m.WhatsappComponent)
      },
      {
        path: 'importar-dados',
        loadComponent: () => import('./components/import-data/import-data.component').then(m => m.ImportDataComponent)
      },
      {
        path: 'simulator',
        loadComponent: () => import('./components/simulator/simulator.component').then(m => m.SimulatorComponent)
      },
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' }
    ]
  },
  { path: '**', redirectTo: 'dashboard' }
];
