import { ScheduleModal } from "@/components/ScheduleModal";
import { useAutoResize } from "@/lib/iframe";

export default function App() {
  useAutoResize();
  return <ScheduleModal />;
}
