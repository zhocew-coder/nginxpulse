import { createRouter, createWebHistory } from 'vue-router';
import { getWebBasePathWithSlash } from '@/utils';

const OverviewPage = () => import('@/pages/OverviewPage.vue');
const DailyPage = () => import('@/pages/DailyPage.vue');
const RealtimePage = () => import('@/pages/RealtimePage.vue');
const LogsPage = () => import('@/pages/LogsPage.vue');
const SetupPage = () => import('@/pages/SetupPage.vue');
const AIPage = () => import('@/pages/AIPage.vue');
const ForecastObjectsPage = () => import('@/pages/ForecastObjectsPage.vue');
const ForecastEventsPage = () => import('@/pages/ForecastEventsPage.vue');
const ForecastOverviewPage = () => import('@/pages/ForecastOverviewPage.vue');
const EventImpactPage = () => import('@/pages/EventImpactPage.vue');

const router = createRouter({
  history: createWebHistory(getWebBasePathWithSlash()),
  routes: [
    {
      path: '/',
      name: 'overview',
      component: OverviewPage,
      meta: {
        sidebarLabelKey: 'app.sidebar.recentActive',
        sidebarHintKey: 'app.sidebar.recentActiveHint',
        mainClass: '',
      },
    },
    {
      path: '/daily',
      name: 'daily',
      component: DailyPage,
      meta: {
        sidebarLabelKey: 'app.menu.daily',
        sidebarHintKey: 'app.sidebar.dailyHint',
        mainClass: 'daily-page',
      },
    },
    {
      path: '/realtime',
      name: 'realtime',
      component: RealtimePage,
      meta: {
        sidebarLabelKey: 'app.menu.realtime',
        sidebarHintKey: 'app.sidebar.realtimeHint',
        mainClass: 'realtime-page',
      },
    },
    {
      path: '/logs',
      name: 'logs',
      component: LogsPage,
      meta: {
        sidebarLabelKey: 'app.menu.logs',
        sidebarHintKey: 'app.sidebar.logsHint',
        mainClass: 'logs-page',
      },
    },
    {
      path: '/settings',
      name: 'settings',
      component: SetupPage,
      props: { mode: 'manage' },
      meta: {
        sidebarLabelKey: 'app.menu.setup',
        sidebarHintKey: 'app.sidebar.setupHint',
        mainClass: 'setup-route',
      },
    },
    {
      path: '/ai',
      name: 'ai',
      component: AIPage,
      meta: {
        sidebarLabelKey: 'app.menu.ai',
        sidebarHintKey: 'app.sidebar.aiHint',
        mainClass: 'ai-page',
      },
    },
    {
      path: '/forecast-objects',
      name: 'forecast-objects',
      component: ForecastObjectsPage,
      // 阶段二新页面：文案全部为中文硬编码（不使用 i18n）
      meta: {
        sidebarLabelKey: '',
        sidebarHintKey: '',
        mainClass: 'forecast-objects-route',
      },
    },
    {
      path: '/forecast-events',
      name: 'forecast-events',
      component: ForecastEventsPage,
      // 阶段四新页面：文案全部为中文硬编码（不使用 i18n）
      meta: {
        sidebarLabelKey: '',
        sidebarHintKey: '',
        mainClass: 'forecast-events-route',
      },
    },
    {
      path: '/forecast-overview',
      name: 'forecast-overview',
      component: ForecastOverviewPage,
      // 阶段六新页面：文案全部为中文硬编码（不使用 i18n），菜单不展示，路由直达
      meta: {
        sidebarLabelKey: '',
        sidebarHintKey: '',
        mainClass: 'forecast-overview-route',
      },
    },
    {
      path: '/event-impact',
      name: 'event-impact',
      component: EventImpactPage,
      // 阶段六新页面：文案全部为中文硬编码（不使用 i18n），菜单不展示，路由直达
      meta: {
        sidebarLabelKey: '',
        sidebarHintKey: '',
        mainClass: 'event-impact-route',
      },
    },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

export default router;
