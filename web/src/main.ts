import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import './style.css'

import HomeView from './views/HomeView.vue'
import JoinView from './views/JoinView.vue'
import RoomView from './views/RoomView.vue'
import PlayView from './views/PlayView.vue'
import ManualView from './views/ManualView.vue'
import EntryView from './views/EntryView.vue'
import ReviewView from './views/ReviewView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/join/:code', component: JoinView },
    { path: '/room', component: RoomView },
    { path: '/play', component: PlayView },
    { path: '/manual', component: ManualView },
    { path: '/entry', component: EntryView },
    { path: '/entry/review', component: ReviewView },
  ],
})

createApp(App).use(createPinia()).use(router).mount('#app')
