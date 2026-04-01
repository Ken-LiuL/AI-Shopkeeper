import { redirect } from 'next/navigation';

export default function ImportsRedirectPage() {
  redirect('/settings/sync');
}
