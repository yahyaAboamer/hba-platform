"use client";
import { RecordPhotos } from '@/components/record-photos';
export function OrderPhotos({orderId,orderCode,canUpload}:{orderId:string;orderCode:string;canUpload:boolean}) {
  return <RecordPhotos recordId={orderId} recordName={orderCode} canUpload={canUpload}/>;
}
