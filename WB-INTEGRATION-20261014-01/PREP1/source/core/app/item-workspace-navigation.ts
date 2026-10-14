import type {Item} from '../lib/domain';
import {createContext,useContext} from 'react';
export const ItemWorkspaceNavigation=createContext<{openAssistant:()=>void;editEntry?:(receipt:import('../lib/work-item-progress').P1ReceiptValue)=>void;openItem:(id:string)=>void;entrySeed?:import('../lib/work-item-progress').P1EntrySeed;saved?:(receipt:Omit<Item,'id'|'title'|'projectIds'|'sourceIds'>,stay:boolean)=>Promise<void>;cancelEntry?:()=>void}|null>(null);
export const useItemWorkspaceNavigation=()=>useContext(ItemWorkspaceNavigation);
