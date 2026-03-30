
export type NotificationType = 'GUEST_ACTIVITY' | 'LEGAL_WARNING' | 'ALERT' | 'SUCCESS';
export type Channel = 'EMAIL' | 'SMS' | 'PUSH' | 'IN_APP';

export interface DocuStayNotification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
  channels: Channel[];
  priority: 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT';
}

class NotificationService {
  private history: DocuStayNotification[] = [];

  getNotifications() {
    return [...this.history];
  }

  send(notification: Omit<DocuStayNotification, 'id' | 'timestamp' | 'read'>) {
    const newNotif: DocuStayNotification = {
      ...notification,
      id: `notif-${Date.now()}`,
      timestamp: new Date().toISOString(),
      read: false
    };
    this.history.unshift(newNotif);
    // In a real app, this would trigger AWS SES, Twilio, etc.
    console.log(`[Notification Sent via ${notification.channels.join(', ')}]: ${notification.title}`);
    return newNotif;
  }

  markAsRead(id: string) {
    this.history = this.history.map(n => n.id === id ? { ...n, read: true } : n);
  }
}

export const notificationService = new NotificationService();
