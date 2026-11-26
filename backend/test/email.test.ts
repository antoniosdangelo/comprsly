import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { relayEmail } from '../src/email.ts'

const raw = (s: string) => new Response(s).body as ReadableStream<Uint8Array>

function capture() {
  const calls: any[] = []
  const fn = (async (_url: string, init: any) => { calls.push(JSON.parse(init.body)); return new Response('{}', { status: 200 }) }) as unknown as typeof fetch
  return { calls, fn }
}

const DMARC = [
  'From: noreply-dmarc-support@google.com',
  'To: contact@comprsly.com',
  'Subject: Report domain: comprsly.com Submitter: google.com',
  'MIME-Version: 1.0',
  'Content-Type: multipart/mixed; boundary="b1"',
  '',
  '--b1',
  'Content-Type: application/zip; name="google.com!comprsly.com!1.zip"',
  'Content-Disposition: attachment; filename="google.com!comprsly.com!1.zip"',
  'Content-Transfer-Encoding: base64',
  '',
  Buffer.from('PK fake zip bytes').toString('base64'),
  '--b1--',
  '',
].join('\r\n')

describe('contact email relay', () => {
  it('carries an attachment-only mail over with its file', async () => {
    const { calls, fn } = capture()
    await relayEmail({ raw: raw(DMARC), from: 'noreply-dmarc-support@google.com' }, { RESEND_API_KEY: 'test' } as any, fn)
    const sent = calls[0]
    assert.equal(sent.attachments.length, 1)
    assert.equal(sent.attachments[0].filename, 'google.com!comprsly.com!1.zip')
    assert.equal(Buffer.from(sent.attachments[0].content, 'base64').toString(), 'PK fake zip bytes')
    assert.match(sent.text, /Attachments: google\.com!comprsly\.com!1\.zip/)
  })

  it('plain text mail still forwards with no attachments field', async () => {
    const { calls, fn } = capture()
    await relayEmail({ raw: raw('From: Pat <pat@example.com>\r\nSubject: hi\r\n\r\nhello there\r\n'), from: 'pat@example.com' }, { RESEND_API_KEY: 'test' } as any, fn)
    assert.equal(calls[0].attachments, undefined)
    assert.equal(calls[0].reply_to, 'pat@example.com')
    assert.match(calls[0].text, /hello there/)
  })

  it('escapes the sender name in the html header', async () => {
    const { calls, fn } = capture()
    const m = 'From: "<b>x</b>" <x@example.com>\r\nSubject: s\r\nContent-Type: text/html\r\n\r\n<p>body</p>\r\n'
    await relayEmail({ raw: raw(m), from: 'x@example.com' }, { RESEND_API_KEY: 'test' } as any, fn)
    assert.doesNotMatch(calls[0].html, /<b>x<\/b>/)
  })
})
