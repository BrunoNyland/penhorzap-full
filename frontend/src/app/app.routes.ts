import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { LoginComponent } from './components/login/login.component';
import { DashboardComponent } from './components/dashboard/dashboard.component';
import { FAQComponent } from './components/faq/faq.component';
import { ConversationsComponent } from './components/conversations/conversations.component';
import { CustomersComponent } from './components/customers/customers.component';
import { ConfigComponent } from './components/config/config.component';
import { WhatsappComponent } from './components/whatsapp/whatsapp.component';
import { SimulatorComponent } from './components/simulator/simulator.component';

export const routes: Routes = [
  { path: 'login', component: LoginComponent },
  {
    path: '',
    canActivate: [authGuard],
    children: [
      { path: 'dashboard', component: DashboardComponent },
      { path: 'faqs', component: FAQComponent },
      { path: 'conversations', component: ConversationsComponent },
      { path: 'customers', component: CustomersComponent },
      { path: 'config', component: ConfigComponent },
      { path: 'whatsapp', component: WhatsappComponent },
      { path: 'simulator', component: SimulatorComponent },
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' }
    ]
  },
  { path: '**', redirectTo: 'dashboard' }
];
