import { CanDeactivateFn } from '@angular/router';

export interface ComponentCanDeactivate {
  hasUnsavedChanges(): boolean;
}

export const unsavedChangesGuard: CanDeactivateFn<ComponentCanDeactivate> = (component) => {
  if (component.hasUnsavedChanges()) {
    return confirm('Você tem alterações não salvas nesta tela. Sair mesmo assim e perdê-las?');
  }
  return true;
};
