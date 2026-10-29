import { createApp } from 'vue';
import App from './App.vue';
import router from './router';
import PrimeVue from 'primevue/config';
import ToastService from 'primevue/toastservice';
import Toast from 'primevue/toast';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import DatePicker from 'primevue/datepicker';
import Dropdown from 'primevue/dropdown';
import InputNumber from 'primevue/inputnumber';
import InputText from 'primevue/inputtext';
import 'primeicons/primeicons.css';
import { getCurrentLocale, i18n, setLocale } from './i18n';
import { primevueLocales } from './i18n/primevue';
import nginxPulsePreset from './styles/primevue-theme';

import './styles/vendor.scss';
import './styles/index.scss';

const app = createApp(App);
app.use(i18n);
app.use(router);
const initialLocale = getCurrentLocale();
app.use(PrimeVue, {
  ripple: true,
  theme: {
    preset: nginxPulsePreset,
    options: {
      darkModeSelector: '.dark-mode',
    },
  },
  locale: primevueLocales[initialLocale],
});
app.use(ToastService);
app.component('Button', Button);
app.component('Checkbox', Checkbox);
app.component('DatePicker', DatePicker);
app.component('Dropdown', Dropdown);
app.component('InputNumber', InputNumber);
app.component('InputText', InputText);
app.component('Toast', Toast);
setLocale(initialLocale, false);
app.mount('#app');
