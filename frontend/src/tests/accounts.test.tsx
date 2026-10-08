// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TransitProvider } from '../components/transit/Shared';
import AccountsPage from '../pages/transit/AccountsPage';
import { patchTransit, postTransit } from '../services/transit';
vi.mock('../services/transit',async original=>{
  const actual=await original<typeof import('../services/transit')>();
  return {...actual,transitRequest:vi.fn(async(path:string)=>path==='/api/buses'?{buses:[{id:'BUS005',registration_number:'TN30-N-1234'}]}:{accounts:[{username:'driver1',role:'driver',bus_id:'BUS005',active:true}]}),postTransit:vi.fn(async()=>({username:'driver2'})),patchTransit:vi.fn(async()=>({active:false}))};
});
afterEach(cleanup);
it('creates an assigned driver and sends an explicit access change',async()=>{
  render(<TransitProvider><AccountsPage/></TransitProvider>);
  await screen.findByRole('cell',{name:'driver1'});
  fireEvent.change(screen.getByLabelText('New username'),{target:{value:'driver2'}});
  fireEvent.change(screen.getByLabelText('New password',{selector:'input[aria-label="New password"]'}),{target:{value:'long-new-password'}});
  fireEvent.click(screen.getByText('Create account'));
  await waitFor(()=>expect(postTransit).toHaveBeenCalledWith('/api/accounts',{username:'driver2',password:'long-new-password',role:'driver',bus_id:'BUS005'}));
  await screen.findByText('Account created.');
  fireEvent.click(screen.getByText('Disable'));
  await waitFor(()=>expect(patchTransit).toHaveBeenCalledWith('/api/accounts/driver1',{active:false}));
});
