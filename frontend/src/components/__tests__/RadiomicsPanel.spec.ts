import { describe, it, expect, beforeEach } from 'vitest'
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

  it('renders execution details (read-only)', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsExecution = mockExecution

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待执行特征提取')
    expect(wrapper.text()).toContain('病例数')
    expect(wrapper.text()).toContain('2')
    expect(wrapper.text()).toContain('Params_labels.yaml')
    expect(wrapper.text()).toContain('p1: images/p1.nii.gz → masks/p1.nii.gz')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('renders plan summary (read-only)', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsPlan = mockPlan

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认配对计划')
    expect(wrapper.text()).toContain('40 / 40')
    expect(wrapper.text()).toContain('高置信 1')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })
})
