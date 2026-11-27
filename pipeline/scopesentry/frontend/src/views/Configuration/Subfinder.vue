<script setup lang="ts">
import { ElRow, ElCol, ElButton } from 'element-plus'
import { useI18n } from '@/hooks/web/useI18n'
import { ElCard } from 'element-plus'
import { ref, onBeforeMount } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { javascript } from '@codemirror/lang-javascript'
import { oneDark } from '@codemirror/theme-one-dark'
import { getSubfinderConfigurationApi, saveSubfinderConfigurationApi } from '@/api/Configuration'
const { t } = useI18n()
const content = ref(``)
const extensions = [javascript(), oneDark]
onBeforeMount(async () => {
  try {
    const res = await getSubfinderConfigurationApi()

    if (res.code === 200) {
      content.value = res.data.content
    } else {
      console.error(`API request failed with status code ${res.code}`)
    }
  } catch (error) {
    console.error('An error occurred while fetching the subfinder config:', error)
  }
})
const confirmAdd = async () => {
  const confirmed = window.confirm('Do you want to save the data?')
  if (confirmed) {
    await save()
  }
}
const save = async () => {
  saveLoading.value = true
  const res = await saveSubfinderConfigurationApi(content.value)
  if (res.code == 200) {
    saveLoading.value = false
  }
}
const saveLoading = ref(false)
</script>

<template>
  <ElCard shadow="never" class="mb-20px">
    <template #header>
      <div class="flex items-center justify-between gap-4">
        <span class="font-medium whitespace-nowrap">{{ t('configuration.subfinder') }}</span>
        <ElButton type="primary" @click="confirmAdd" @loading="saveLoading">{{
          t('common.save')
        }}</ElButton>
      </div>
    </template>
    <codemirror
      v-model="content"
      :style="{ height: '800px' }"
      :autofocus="true"
      :indent-with-tab="true"
      :tab-size="2"
      :extensions="extensions"
    />
  </ElCard>
</template>

<style scoped>
.header-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}
</style>
