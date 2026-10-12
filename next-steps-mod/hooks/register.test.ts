import { expect, test } from 'claude-code/testing'

// Idle session: no turn has completed, so the band must draw nothing of its own,
// on every surface.
for (const surface of ['terminal', 'desktop'] as const) {
  test(`draws no suggestions before a turn completes (${surface})`, async ($, on) => {
    on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
      const { Box } = $.ui.resolve(e)
      return Box({}) as never
    })
    const ui = await $.ui.mount({
      plugin: 'next-steps-mod',
      surface,
      component: 'AbovePrompt',
      props: { hasSurvey: false, isWorking: false },
    })
    expect(await ui.findAll({ type: 'Button' })).toEqual([])
  })
}
