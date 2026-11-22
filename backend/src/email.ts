import PostalMime from 'postal-mime'
import type { EmailMessage, Env } from './types.ts'

const FORWARD_TO = 'antoniosdangeloo@gmail.com'
const SEND_FROM = 'Comprsly Contact <contact@comprsly.com>'

/**
 * Relays mail sent to contact@comprsly.com on to a real inbox.
 *
 * Why Resend rather than Cloudflare's own forwarding: a plain forward kept
 * failing Gmail's DMARC check on Gmail-to-Gmail mail. Resend re-sends from a
 * domain that passes, with reply_to pointed back at the original sender, so
 * replying still reaches the right person. Found and fixed 2026-07-27.
 */
export async function relayEmail(message: EmailMessage, env: Env): Promise<void> {
  const email = await PostalMime.parse(message.raw)
  const senderName = email.from?.name || email.from?.address || message.from
  const senderAddress = email.from?.address || message.from

  const response = await fetch('https://api.resend.com/emails', {
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
      text: `From: ${senderName} <${senderAddress}>\n\n${email.text ?? ''}`,
      html: email.html
        ? `<p><strong>From:</strong> ${senderName} &lt;${senderAddress}&gt;</p><hr>${email.html}`
        : undefined,
    }),
  })

  if (!response.ok) {
    const body = await response.text()
    console.error('Resend send failed:', response.status, body)
    throw new Error(`Resend API error: ${response.status}`)
  }
}
