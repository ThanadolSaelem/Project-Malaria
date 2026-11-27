<script setup lang="ts">
import { useI18n } from '@/hooks/web/useI18n'
import { ElTabs } from 'element-plus'
import { ElTabPane } from 'element-plus'
import AssetInfo2 from './components/AssetInfo2.vue'
import Subdomain from './components/Subdomain.vue'
import URL from './components/URL.vue'
import Crawler from './components/Crawler.vue'
import SensitiveInformation from './components/SensitiveInformation.vue'
import DirScan from './components/DirScan.vue'
import PageMonitoring from './components/PageMonitoring.vue'
import vul from './components/vul.vue'
import SubdomainTakeover from './components/SubdomainTakeover.vue'
import { reactive } from 'vue'
import { getProjectAllApi } from '@/api/project'
import { getTaskNamesApi } from '@/api/task'
import RootDomain from './components/RootDomain.vue'
import APP from './components/APP.vue'
import MP from './components/MP.vue'
import IP from './components/IP.vue'
import { navigateScopeSentry } from '@/runtime'
const { t } = useI18n()
interface Project {
  value: string
  label: string
  children?: Project[]
}
const projectList = reactive<Project[]>([])
const getProjectList = async () => {
  const res = await getProjectAllApi()
  res.data.list.forEach((item: Project) => {
    projectList.push(item)
  })
}
getProjectList()

interface TaskNameData {
  id: string
  name: string
}
const taskList = reactive<TaskNameData[]>([])
const getTaskList = async () => {
  const res = await getTaskNamesApi()
  taskList.splice(0, taskList.length, ...(res.data || []))
}
getTaskList()

const handleTabClick = (tab: any) => {
  if (tab.paneName === 'map') {
    // 跳转到同一网站的map项目
    navigateScopeSentry('/map')
  }
}
</script>

<template>
  <ElTabs type="border-card" @tab-click="handleTabClick">
    <ElTabPane :label="t('asset.assetName')" lazy
      ><AssetInfo2 :projectList="projectList" :taskList="taskList"
    /></ElTabPane>
    <ElTabPane label="IP" lazy><IP :projectList="projectList" :taskList="taskList" /></ElTabPane>
    <ElTabPane :label="t('rootDomain.rootDomainName')" lazy>
      <RootDomain :projectList="projectList" :taskList="taskList" />
    </ElTabPane>
    <ElTabPane :label="t('subdomain.subdomainName')" lazy>
      <Subdomain :projectList="projectList" :taskList="taskList" />
    </ElTabPane>
    <ElTabPane :label="t('task.subdomainTakeover')" lazy>
      <SubdomainTakeover :projectList="projectList" :taskList="taskList" />
    </ElTabPane>
    <ElTabPane :label="t('app.appName')" lazy>
      <APP :projectList="projectList" :taskList="taskList" />
    </ElTabPane>
    <ElTabPane :label="t('miniProgram.miniProgramName')" lazy>
      <MP :projectList="projectList" :taskList="taskList" />
    </ElTabPane>
    <ElTabPane :label="t('URL.URLName')" lazy
      ><URL :projectList="projectList" :taskList="taskList"
    /></ElTabPane>
    <ElTabPane :label="t('crawler.crawlerName')" lazy
      ><Crawler :projectList="projectList" :taskList="taskList"
    /></ElTabPane>
    <ElTabPane :label="t('sensitiveInformation.sensitiveInformationName')" lazy>
      <SensitiveInformation :projectList="projectList" :taskList="taskList" />
    </ElTabPane>
    <ElTabPane :label="t('dirScan.dirScanName')" lazy
      ><DirScan :projectList="projectList" :taskList="taskList"
    /></ElTabPane>
    <ElTabPane :label="t('vulnerability.vulnerabilityName')" lazy>
      <vul :projectList="projectList" :taskList="taskList" />
    </ElTabPane>
    <ElTabPane :label="t('PageMonitoring.pageMonitoringName')" lazy>
      <PageMonitoring :projectList="projectList" :taskList="taskList" />
    </ElTabPane>
    <ElTabPane label="Map" name="map" />
  </ElTabs>
</template>
