import PostalMime from 'postal-mime'
import type { EmailMessage, Env } from './types.ts'

const FORWARD_TO = 'antoniosdangeloo@gmail.com'
const SEND_FROM = 'Comprsly Contact <contact@comprsly.com>'
// Resend caps a whole email at 40 MB, and base64 grows a file by a third. Bigger mail goes on without its files and says so.
const MAX_ATTACH_BYTES = 25 * 1024 * 1024

/**
 * Relays mail sent to contact@comprsly.com on to a real inbox.
 *
 * Why Resend rather than Cloudflare's own forwarding: a plain forward kept
 * failing Gmail's DMARC check on Gmail-to-Gmail mail. Resend re-sends from a
 * domain that passes, with reply_to pointed back at the original sender, so
 * replying still reaches the right person. Found and fixed 2026-07-27.
 *
 * Attachments are carried over (2026-11-25). Before that they were dropped, so
 * mail that is only an attachment, like Google's DMARC reports, arrived empty.
 */
export async function relayEmail(message: EmailMessage, env: Env, fetchFn: typeof fetch = fetch): Promise<void> {
  const email = await PostalMime.parse(message.raw)
  const senderName = email.from?.name || email.from?.address || message.from
  const senderAddress = email.from?.address || message.from

  const files = (email.attachments || []).map((a) => ({ filename: a.filename || 'attachment', bytes: toBytes(a.content) }))
  const total = files.reduce((n, f) => n + f.bytes.byteLength, 0)
  const keepFiles = total <= MAX_ATTACH_BYTES
  const note = files.length === 0 ? '' : keepFiles
    ? `Attachments: ${files.map((f) => f.filename).join(', ')}`
    : `Attachments were too large to forward (${files.length} files, ${Math.round(total / 1048576)} MB). Open the original sender's mail for them.`

  const header = `From: ${senderName} <${senderAddress}>`
  const text = [header, note, email.text ?? ''].filter(Boolean).join('\n\n')
  const html = email.html
    ? `<p><strong>From:</strong> ${escapeHtml(senderName)} &lt;${escapeHtml(senderAddress)}&gt;</p>${note ? `<p>${escapeHtml(note)}</p>` : ''}<hr>${email.html}`
    : undefined

  const response = await fetchFn('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: SEND_FROM,
      to: [FORWARD_TO],
      reply_to: senderAddress,
      subject: email.subject || '(no subject)',
      text,
      html,
      attachments: keepFiles && files.length ? files.map((f) => ({ filename: f.filename, content: toBase64(f.bytes) })) : undefined,
    }),
  })

  if (!response.ok) {
    const body = await response.text()
    console.error('Resend send failed:', response.status, body)
    throw new Error(`Resend API error: ${response.status}`)
  }
}

function toBytes(c: ArrayBuffer | Uint8Array | string): Uint8Array {
  if (typeof c === 'string') return new TextEncoder().encode(c)
  return c instanceof Uint8Array ? c : new Uint8Array(c)
}

function toBase64(bytes: Uint8Array): string {
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(bin)
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
