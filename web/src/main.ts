import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import { loadNickname } from './store'

import WelcomeView from './views/WelcomeView.vue'
import LobbyView from './views/LobbyView.vue'
import JoinView from './views/JoinView.vue'
import RoomView from './views/RoomView.vue'
import PlayView from './views/PlayView.vue'
import ManualView from './views/ManualView.vue'
import EntryView from './views/EntryView.vue'
import ReviewView from './views/ReviewView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: LobbyView },
    { path: '/welcome', component: WelcomeView },
    { path: '/join/:code', component: JoinView },
    { path: '/room', component: RoomView },
    { path: '/play', component: PlayView },
    { path: '/manual', component: ManualView },
    { path: '/entry', component: EntryView },
    { path: '/entry/review', component: ReviewView },
  ],
})

// 首次进入需先设昵称；深链加入页自带昵称输入，故放行。
const NICK_FREE = ['/welcome', '/manual', '/entry', '/entry/review']
router.beforeEach((to) => {
  if (loadNickname()) return true
  if (NICK_FREE.includes(to.path) || to.path.startsWith('/join/')) return true
  return { path: '/welcome', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
})

createApp(App).use(createPinia()).use(router).mount('#app')
