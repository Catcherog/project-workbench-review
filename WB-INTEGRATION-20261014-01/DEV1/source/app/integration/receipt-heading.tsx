"use client";
import { receiptPresentation, receiptTimestamp, type SavedReceipt } from './receipt-presentation';
/** Presentational replacement inside P1Receipt. Existing undo/version/conflict callbacks stay in the original component. */
export function IntegrationReceiptHeading({receipt}: {receipt: SavedReceipt}) {
  const view = receiptPresentation(receipt);
  return <header className="wb-int-receipt-heading" data-tone={view.tone}>
    <strong>{view.title}</strong>
    <small>{receiptTimestamp(receipt.at)} · 保存记录</small>
  </header>;
}
