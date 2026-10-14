import React from 'react';
import { createRoot } from 'react-dom/client';
import Workbench from './workbench-v2';
import { DeskPetWindow } from './desk-pet-window';
const petMode=new URLSearchParams(location.search).get('pet')==='1';
if(petMode)document.documentElement.classList.add('pet-mode');
createRoot(document.getElementById('root')!).render(<React.StrictMode>{petMode?<DeskPetWindow/>:<Workbench />}</React.StrictMode>);
