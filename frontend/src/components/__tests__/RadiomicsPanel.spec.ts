import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import RadiomicsPanel from '../RadiomicsPanel.vue'
import { useAgentStore } from '@/stores/agent'

function setupWrapper() {
  return mount(RadiomicsPanel, {
    global: {
      plugins: [ElementPlus],
    },
  })
}

const mockExecution = {
  tool_call_id: 'tc1',
  pairs: [
    { patient_id: 'p1', image_path: 'images/p1.nii.gz', mask_path: 'masks/p1.nii.gz' },
    { patient_id: 'p2', image_path: 'images/p2.nii.gz', mask_path: 'masks/p2.nii.gz' },
  ],
  n_cases: 2,
  yaml_path: 'Params_labels.yaml',
  output_dir: 'radiomics_features',
}

const mockPlan = {
  tool_call_id: 'tc2',
  _pending_tool: 'discover_radiomics_pairs',
  success: true,
  images_found: 40,
  masks_found: 40,
  pairs: {
    high: [{ patient_id: 'p1', image_path: 'images/p1.nii.gz', mask_path: 'masks/p1.nii.gz' }],
    medium: [],
    low: [],
  },
  unmatched_images: [],
  unmatched_masks: [],
}

describe('RadiomicsPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders execution details and confirm triggers store.confirm', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsExecution = mockExecution
    const confirmSpy = vi.spyOn(store, 'confirm').mockResolvedValue(undefined)

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待执行特征提取')
    expect(wrapper.text()).toContain('病例数')
    expect(wrapper.text()).toContain('2')
    expect(wrapper.text()).toContain('Params_labels.yaml')
    expect(wrapper.text()).toContain('p1: images/p1.nii.gz → masks/p1.nii.gz')

    const confirmButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('确认提取'))
    expect(confirmButton).toBeDefined()
    await confirmButton!.trigger('click')
    expect(confirmSpy).toHaveBeenCalled()
  })

  it('renders plan summary and cancel triggers store.cancel', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsPlan = mockPlan
    const cancelSpy = vi.spyOn(store, 'cancel').mockResolvedValue(undefined)

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认配对计划')
    expect(wrapper.text()).toContain('40 / 40')
    expect(wrapper.text()).toContain('高置信 1')

    const cancelButton = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === '取消')
    expect(cancelButton).toBeDefined()
    await cancelButton!.trigger('click')
    expect(cancelSpy).toHaveBeenCalled()
  })
})
