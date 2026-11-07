"use client";
import type { ProductionOrder } from "@/lib/demo-data";
import { Badge, TableWrap, statusTone } from "@/components/ui";

export function ManufacturingTracker({orders,navigate}:{orders:ProductionOrder[];navigate:(path:string)=>void}) {
  const rows = [...orders].sort((a,b)=>(a.trackerOrderNumber ?? Number.MAX_SAFE_INTEGER)-(b.trackerOrderNumber ?? Number.MAX_SAFE_INTEGER));
  return <TableWrap><table className="manufacturing-tracker"><caption className="sr-only">Manufacturing orders with fabric weight, size quantities and estimated completion dates</caption><thead><tr>{['Order No','Start Date','Model','Product SKU / style','Supplier','Fabric','KG','Color','Status','Quantity','S','M','L','XL','XXL','Est. Completion'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map(order=>{
    const label = order.status==='Completed' || order.status==='Warehouse Received' ? 'Completed' : order.status==='Not Started' || order.status==='Pending Approval' ? 'Waiting' : order.status==='In Progress' || order.status==='On Track' ? 'In Production' : order.status;
    const colors:Record<string,string> = {realtree:'#397329','أسود':'#111111','شانيه':'#8f9198','نبيتي':'#8a2437','بني':'#965b21','رمادي':'#6b7280',WASHED:'#a3a3a3'};
    return <tr key={order.id} className="clickable-row" onClick={()=>navigate(`/production-orders/${order.code}`)}>
      <td><button className="text-button mono-cell" onClick={event=>{event.stopPropagation();navigate(`/production-orders/${order.code}`);}} aria-label={`Open order ${order.trackerOrderNumber ?? order.code}`}>{order.trackerOrderNumber ?? order.code}</button></td>
      <td>{order.startDate}</td><td><strong>{order.trackerModel || order.product}</strong></td><td><button className="text-button mono-cell" onClick={event=>{event.stopPropagation();navigate(`/products/${encodeURIComponent(order.style)}`);}}>{order.style}</button></td><td dir="auto">{order.supplier}</td><td dir="auto">{order.fabric || '—'}</td><td className="tracker-number">{order.fabricKg == null ? '—' : order.fabricKg.toFixed(1)}</td>
      <td><span className="tracker-color"><i aria-hidden="true" style={{background:colors[order.color] || '#64748b'}}/><span dir="auto">{order.color}</span></span></td><td><Badge tone={statusTone(order.status)}>{label}</Badge></td><td className="tracker-number"><strong>{order.quantity}</strong></td>{['S','M','L','XL','XXL'].map(size=><td className="tracker-number" key={size}>{order.sizeBreakdown[size] ?? '—'}</td>)}<td>{order.forecastDelivery}</td>
    </tr>;
  })}{!rows.length && <tr><td colSpan={16}>No orders match these filters.</td></tr>}</tbody></table></TableWrap>;
}
